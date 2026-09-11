#!/usr/bin/env python3
"""
Enrich the crawled sites from Wikimedia: article text, readership, photographs.

Three things, all from APIs that are open and citable, and all keyed on the
`wikidata` table the label stage already built (1,660 Swedish articles and 221
English ones across the whole register -- so this runs over every site we
crawled, not over whichever ten thousand the exporter picked today).

    EXTRACTS    The lead paragraphs of the Wikipedia article. Fornsok tells you
                what is physically on the ground, in a surveyor's words;
                Wikipedia tells you why the place matters. Different questions,
                and a visitor wants both.

    PAGEVIEWS   How many people read that article in the last twelve months,
                and this is the point of the whole script. Every signal the
                score currently uses measures DOCUMENTATION -- somebody wrote,
                photographed or catalogued the place. Pageviews measure the
                public. It is the only number here that is not a proxy for how
                well recorded a site is, which is exactly the bias the score
                has today (2,048 Wikidata sitelinks and 3,136 images against 40
                hand judgements).

    PHOTOS      Commons images, found two ways: the image Wikidata designates
                for the item, and a geosearch around the site's coordinate.
                Each row carries its own licence and author, because Commons
                files are licensed individually -- CC0, CC BY, CC BY-SA and
                public domain all appear in the same result set, so a single
                blanket attribution would be wrong for most of them.

LICENSING, briefly, because it decides the schema. The K-samsok register is
CC0: we can rewrite it, ship it and owe nobody anything. Wikipedia text is
CC BY-SA 4.0, which travels to adaptations -- so a generated description that
drew on an article must say so and carries share-alike. That obligation is per
description, not global, so it is tracked per row rather than avoided. Raw
extracts are kept here, separate from the generated text, so the number and
purple-prose checks in describe_place.py can be run against each source on its
own; blending two sources into one paragraph is how you lose the ability to
say where a wrong fact came from, and that check is the one that caught a
hallucinated "40 skalgropar".

Resumable and safe to re-run: every fetch is cached with a timestamp and
skipped while fresh.

Usage:
    python crawl_wikimedia.py --status
    python crawl_wikimedia.py --extracts
    python crawl_wikimedia.py --pageviews
    python crawl_wikimedia.py --photos
    python crawl_wikimedia.py --all
"""

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

SITES_DB = "src/data/sites.sqlite"
OUT_DB = "src/data/wikimedia.sqlite"

# Wikimedia asks for a descriptive User-Agent with contact details and blocks
# generic ones outright. This is not politeness, it is a hard requirement.
UA = ("fornlamningar-pipeline/1.0 "
      "(https://github.com/framay/fornlamningar; franco.may@etraveligroup.com)")

# Well inside Wikimedia's published limits for anonymous use. The whole job is
# a few thousand requests, so there is nothing to gain by pushing it.
DELAY = 0.12
MAX_RETRY = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_articles (
    uuid        TEXT NOT NULL,
    lang        TEXT NOT NULL,          -- 'sv' | 'en'
    title       TEXT NOT NULL,
    extract     TEXT,                   -- lead paragraphs, CC BY-SA 4.0
    url         TEXT,
    -- Readership over the trailing twelve whole months. NULL means not
    -- fetched yet; 0 means fetched and genuinely unread, which is itself a
    -- useful thing to know about a site.
    views_12m   INTEGER,
    views_from  TEXT,
    views_to    TEXT,
    fetched_at  TEXT,
    PRIMARY KEY (uuid, lang)
);
CREATE INDEX IF NOT EXISTS idx_wa_views ON wiki_articles(views_12m DESC);

CREATE TABLE IF NOT EXISTS photos (
    uuid         TEXT NOT NULL,
    file         TEXT NOT NULL,         -- 'File:Bohus fastning 101.JPG'
    -- How we decided this photo belongs to this site. 'wikidata' is the image
    -- the item itself designates and is as certain as we get. 'geosearch' is
    -- a Commons file whose own coordinates fall within GEO_RADIUS_M, which is
    -- a guess -- a good one, but a guess -- so the two are never mixed.
    source       TEXT NOT NULL,
    distance_m   REAL,
    page_url     TEXT,
    thumb_url    TEXT,
    image_url    TEXT,
    width        INTEGER,
    height       INTEGER,
    licence      TEXT,
    licence_url  TEXT,
    author       TEXT,
    -- Ready-made credit line from Commons where the uploader supplied one.
    credit       TEXT,
    fetched_at   TEXT,
    PRIMARY KEY (uuid, file)
);
CREATE INDEX IF NOT EXISTS idx_ph_uuid ON photos(uuid);

CREATE TABLE IF NOT EXISTS failures (
    uuid    TEXT NOT NULL,
    stage   TEXT NOT NULL,
    error   TEXT,
    at      TEXT,
    PRIMARY KEY (uuid, stage)
);
"""

# Commons files carry their own coordinates, and a photograph taken of a site
# is rarely standing on it. 500 m is wide enough for a picture shot from the
# far side of a grave field and tight enough that the next farm's barn does
# not land in the wrong record.
GEO_RADIUS_M = 500
# More than this and they are almost certainly not all of the same thing.
MAX_PHOTOS_PER_SITE = 8


def get(url, params=None, retries=MAX_RETRY):
    """GET returning parsed JSON, with backoff. None on give-up."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 404 is an answer, not a failure: the article or the file is gone.
            if e.code == 404:
                return None
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"__error": f"HTTP {e.code}"}
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"__error": str(e)[:200]}
    return None


def open_out():
    conn = sqlite3.connect(OUT_DB)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def title_of(url):
    """Article title out of a sitelink URL.

    The `wikidata` table stores full percent-encoded URLs, not titles --
    `https://sv.wikipedia.org/wiki/Stj%C3%A4rneborg_(observatorium)` -- which
    is what Wikidata's sitelinks give you. Feeding those to the REST endpoints
    as if they were titles produced a clean 404 on every extract and a
    plausible-looking zero on every pageview count, which is the worse of the
    two failures: nothing errored, the numbers just came back uniformly
    uninteresting.
    """
    if not url:
        return None
    slug = url.rstrip("/").rsplit("/wiki/", 1)[-1]
    return urllib.parse.unquote(slug).replace("_", " ") or None


def image_title(url):
    """'File:X.jpg' out of a Wikidata P18 Special:FilePath URL."""
    if not url:
        return None
    name = url.rstrip("/").rsplit("/", 1)[-1]
    name = urllib.parse.unquote(name).replace("_", " ")
    return f"File:{name}" if name else None


def articles(sites):
    """(uuid, lang, title) for every crawled site with a Wikipedia article."""
    rows = sites.execute("""
        SELECT uuid, sv_wiki, en_wiki FROM wikidata
        WHERE (sv_wiki IS NOT NULL AND sv_wiki <> '')
           OR (en_wiki IS NOT NULL AND en_wiki <> '')
    """).fetchall()
    out = []
    for uuid, sv, en in rows:
        # Swedish first and preferred: it is the register's language, the
        # articles are longer for Swedish sites, and the app is Swedish.
        sv, en = title_of(sv), title_of(en)
        if sv:
            out.append((uuid, "sv", sv))
        if en:
            out.append((uuid, "en", en))
    return out


def fetch_extracts(sites, out, limit=None):
    todo = [(u, l, t) for u, l, t in articles(sites)
            if not out.execute("SELECT 1 FROM wiki_articles WHERE uuid=? "
                               "AND lang=? AND extract IS NOT NULL",
                               (u, l)).fetchone()]
    if limit:
        todo = todo[:limit]
    print(f"extracts: {len(todo):,} to fetch")
    done = 0
    for i, (uuid, lang, title) in enumerate(todo, 1):
        # The REST summary endpoint rather than action=query&prop=extracts: it
        # returns the lead already cleaned of templates and infobox debris,
        # which is what action=query hands back and what would otherwise have
        # to be stripped here with regexes that go stale.
        j = get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
                + urllib.parse.quote(title.replace(" ", "_"), safe=""))
        if j is None:
            record_failure(out, uuid, f"extract:{lang}", "404")
        elif "__error" in j:
            record_failure(out, uuid, f"extract:{lang}", j["__error"])
        else:
            out.execute("""
                INSERT INTO wiki_articles (uuid, lang, title, extract, url,
                                           fetched_at)
                VALUES (?,?,?,?,?,datetime('now'))
                ON CONFLICT(uuid, lang) DO UPDATE SET
                    title=excluded.title, extract=excluded.extract,
                    url=excluded.url, fetched_at=excluded.fetched_at
            """, (uuid, lang, title, j.get("extract"),
                  ((j.get("content_urls") or {}).get("desktop") or {}).get("page")))
            done += 1
        if i % 100 == 0:
            out.commit()
            print(f"  {i:,}/{len(todo):,}")
        time.sleep(DELAY)
    out.commit()
    print(f"  {done:,} extracts stored")


def month_range():
    """The last twelve WHOLE months, as the pageviews API wants them.

    Whole months only, and not a trailing 365 days, because a partial current
    month would make every site fetched later in the month score higher than
    one fetched on the 1st -- a ranking that moves with the calendar rather
    than with the data.
    """
    first_of_this = date.today().replace(day=1)
    end = first_of_this
    start = end
    for _ in range(12):
        start = (start - timedelta(days=1)).replace(day=1)
    return start.strftime("%Y%m%d00"), end.strftime("%Y%m%d00"), start, end


def fetch_pageviews(sites, out, limit=None):
    start, end, d0, d1 = month_range()
    todo = [(u, l, t) for u, l, t in articles(sites)
            if not out.execute("SELECT 1 FROM wiki_articles WHERE uuid=? AND "
                               "lang=? AND views_12m IS NOT NULL AND views_to=?",
                               (u, l, d1.isoformat())).fetchone()]
    if limit:
        todo = todo[:limit]
    print(f"pageviews: {len(todo):,} to fetch  "
          f"({d0.isoformat()} .. {d1.isoformat()})")
    for i, (uuid, lang, title) in enumerate(todo, 1):
        art = urllib.parse.quote(title.replace(" ", "_"), safe="")
        j = get("https://wikimedia.org/api/rest_v1/metrics/pageviews/"
                f"per-article/{lang}.wikipedia/all-access/user/{art}/monthly/"
                f"{start}/{end}")
        # A 404 here means the article exists but has no recorded views in the
        # window, so zero is the honest value -- not missing data.
        views = 0
        if j and "__error" in j:
            record_failure(out, uuid, f"views:{lang}", j["__error"])
            views = None
        elif j:
            views = sum(x.get("views", 0) for x in j.get("items", []))
        if views is not None:
            out.execute("""
                INSERT INTO wiki_articles (uuid, lang, title, views_12m,
                                           views_from, views_to, fetched_at)
                VALUES (?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(uuid, lang) DO UPDATE SET
                    views_12m=excluded.views_12m,
                    views_from=excluded.views_from, views_to=excluded.views_to,
                    fetched_at=excluded.fetched_at
            """, (uuid, lang, title, views, d0.isoformat(), d1.isoformat()))
        if i % 200 == 0:
            out.commit()
            print(f"  {i:,}/{len(todo):,}")
        time.sleep(DELAY)
    out.commit()
    top = out.execute("SELECT title, views_12m FROM wiki_articles "
                      "WHERE views_12m IS NOT NULL "
                      "ORDER BY views_12m DESC LIMIT 5").fetchall()
    print("  most read:")
    for t, v in top:
        print(f"    {v:>9,}  {t}")


def commons_meta(j):
    """(licence, licence_url, author, credit) out of Commons extmetadata."""
    import re
    em = j.get("extmetadata") or {}

    def val(k):
        v = (em.get(k) or {}).get("value")
        # Commons stores these as HTML fragments -- author fields regularly
        # contain a whole <a> tag plus a span. Strip to text; a credit line
        # with markup in it is worse than a plain name.
        return re.sub(r"<[^>]+>", "", v).strip() if isinstance(v, str) else None

    return val("LicenseShortName"), val("LicenseUrl"), val("Artist"), val("Credit")


def fetch_photos(sites, out, limit=None):
    rows = sites.execute("""
        SELECT w.uuid, w.image, s.lon, s.lat
        FROM wikidata w JOIN sites s ON s.uuid = w.uuid
        WHERE s.lon IS NOT NULL
          AND ((w.image IS NOT NULL AND w.image <> '')
               OR (w.sitelinks IS NOT NULL AND w.sitelinks > 0))
    """).fetchall()
    todo = [r for r in rows
            if not out.execute("SELECT 1 FROM photos WHERE uuid=?",
                               (r[0],)).fetchone()]
    if limit:
        todo = todo[:limit]
    print(f"photos: {len(todo):,} sites to look up")
    n_files = 0
    for i, (uuid, image, lon, lat) in enumerate(todo, 1):
        found = {}

        # 1. The image the Wikidata item itself designates. As certain as this
        #    gets, so it wins on conflict.
        wd_file = image_title(image)
        if wd_file:
            found[wd_file] = ("wikidata", None)

        # 2. Whatever Commons has within GEO_RADIUS_M of the site.
        j = get("https://commons.wikimedia.org/w/api.php", {
            "action": "query", "format": "json", "generator": "geosearch",
            "ggscoord": f"{lat}|{lon}", "ggsradius": GEO_RADIUS_M,
            "ggslimit": MAX_PHOTOS_PER_SITE, "ggsnamespace": 6,
        })
        if j and "__error" not in j:
            for p in ((j.get("query") or {}).get("pages") or {}).values():
                t = p.get("title")
                if t and t not in found:
                    found[t] = ("geosearch", None)

        if not found:
            time.sleep(DELAY)
            continue

        # One metadata request for every file of this site at once.
        titles = "|".join(list(found)[:MAX_PHOTOS_PER_SITE + 1])
        j = get("https://commons.wikimedia.org/w/api.php", {
            "action": "query", "format": "json", "titles": titles,
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata", "iiurlwidth": 640,
        })
        if not j or "__error" in j:
            record_failure(out, uuid, "photos",
                           (j or {}).get("__error", "no response"))
            time.sleep(DELAY)
            continue

        for p in ((j.get("query") or {}).get("pages") or {}).values():
            ii = (p.get("imageinfo") or [None])[0]
            if not ii:
                continue
            title = p.get("title")
            src = found.get(title, ("geosearch", None))[0]
            lic, lic_url, author, credit = commons_meta(ii)
            out.execute("""
                INSERT OR REPLACE INTO photos
                  (uuid, file, source, distance_m, page_url, thumb_url,
                   image_url, width, height, licence, licence_url, author,
                   credit, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            """, (uuid, title, src, None, ii.get("descriptionurl"),
                  ii.get("thumburl"), ii.get("url"), ii.get("width"),
                  ii.get("height"), lic, lic_url, author, credit))
            n_files += 1

        if i % 50 == 0:
            out.commit()
            print(f"  {i:,}/{len(todo):,}  ({n_files:,} files)")
        time.sleep(DELAY)
    out.commit()
    print(f"  {n_files:,} photo rows")


def record_failure(out, uuid, stage, error):
    out.execute("INSERT OR REPLACE INTO failures (uuid, stage, error, at) "
                "VALUES (?,?,?,datetime('now'))", (uuid, stage, error))


def status(sites, out):
    total = len(articles(sites))
    print(f"{total:,} (site, language) article pairs in the register")
    for lang in ("sv", "en"):
        n = out.execute("SELECT COUNT(*) FROM wiki_articles WHERE lang=? "
                        "AND extract IS NOT NULL", (lang,)).fetchone()[0]
        v = out.execute("SELECT COUNT(*) FROM wiki_articles WHERE lang=? "
                        "AND views_12m IS NOT NULL", (lang,)).fetchone()[0]
        print(f"  {lang}: {n:,} extracts, {v:,} with pageviews")
    ph, sites_ph = out.execute(
        "SELECT COUNT(*), COUNT(DISTINCT uuid) FROM photos").fetchone()
    print(f"  {ph:,} photos across {sites_ph:,} sites")
    for src, n in out.execute("SELECT source, COUNT(*) FROM photos "
                              "GROUP BY 1 ORDER BY 2 DESC"):
        print(f"    {src}: {n:,}")
    print("  licences:")
    for lic, n in out.execute("SELECT COALESCE(licence,'(unknown)'), COUNT(*) "
                              "FROM photos GROUP BY 1 ORDER BY 2 DESC LIMIT 8"):
        print(f"    {lic}: {n:,}")
    f = out.execute("SELECT stage, COUNT(*) FROM failures GROUP BY 1").fetchall()
    if f:
        print("  failures:")
        for s, n in f:
            print(f"    {s}: {n:,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sites-db", default=SITES_DB)
    p.add_argument("--out", default=OUT_DB)
    p.add_argument("--extracts", action="store_true")
    p.add_argument("--pageviews", action="store_true")
    p.add_argument("--photos", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--status", action="store_true")
    p.add_argument("--limit", type=int, default=None,
                   help="stop after N items; for a quick smoke test")
    args = p.parse_args()

    if not os.path.exists(args.sites_db):
        sys.exit(f"missing {args.sites_db} -- run the pipeline first")
    sites = sqlite3.connect(f"file:{args.sites_db}?mode=ro", uri=True)
    out = open_out()

    if args.status or not (args.extracts or args.pageviews or args.photos
                           or args.all):
        status(sites, out)
        return
    if args.extracts or args.all:
        fetch_extracts(sites, out, args.limit)
    if args.pageviews or args.all:
        fetch_pageviews(sites, out, args.limit)
    if args.photos or args.all:
        fetch_photos(sites, out, args.limit)
    print()
    status(sites, out)


if __name__ == "__main__":
    main()
