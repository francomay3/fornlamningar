"""Assemble places.sqlite -- the product.

Everything upstream of this file is either something we downloaded or a
measurement we took. This is where those become one row per place a person
could decide to visit, with the text, the pictures and the provenance of
both, and nothing that only made sense to the machinery that produced it.

Reads:  work.sqlite       clusters, scores, sites      (cheap, rebuildable)
        generated.sqlite  our descriptions, sv + en    (13 h of model time)
        wikimedia.sqlite  Commons photos with licences
        lansstyrelsen.sqlite   sign and parking status
Writes: places.sqlite     features, images
        (build_sources.py writes `sources` and `generation_sources` into the
         same file -- the corpus is part of the product, not a side table)

Deliberately NOT here:
  stars     A quantile of whatever set got exported. Export 5,000 instead of
            10,000 and every star changes without a single place changing, so
            a star is a property of the tile, not of the place. `score` is
            here; the bucketing happens in build_tiles.py.
  signals   The features a model was fitted on. They belong next to the model
            that consumes them, in work.sqlite, and putting them here would
            invite reading a fitted intermediate as if it were a fact about
            the place.
"""

import argparse
import os
import sqlite3

import paths
from crawl_lansstyrelsen import plan_clusters
from families import FAMILY

SCHEMA = """
CREATE TABLE IF NOT EXISTS features (
    cluster_id   TEXT PRIMARY KEY,
    lon          REAL, lat REAL,
    -- Identity as a visitor would recognise it.
    name         TEXT,               -- folk name, when the register has one
    title        TEXT,               -- generated, Swedish (canonical)
    content      TEXT,
    title_en     TEXT,               -- generated, second pass over the above
    content_en   TEXT,
    class_sv     TEXT,               -- dominant class of the cluster
    family       TEXT,               -- families.py id, not a label
    n_sites      INTEGER,            -- register rows inside this place
    lamningsnummer TEXT,
    raa_url      TEXT,
    parish       TEXT, municipality TEXT, county TEXT,

    score        REAL,
    excluded     INTEGER,            -- hard or soft, collapsed for the app

    -- Three states, and the third is an answer rather than a gap: 31 of the
    -- 122 plans simply do not say. TRUE means "there is a sign OR the county
    -- judged none is needed" -- one fact for a visitor, because a Minnessten
    -- is a stone with the text carved into it and a Stenvalvbro is a bridge
    -- you walk across. FALSE is "a sign is needed and is not there", which
    -- is what "Problem" turns out to mean once you read the comments
    -- ("Skylt krävs", "Hänvisning och infoskylt behövs!").
    has_or_doesnt_need_sign     INTEGER,
    has_or_doesnt_need_parking  INTEGER,
    -- The county's own words, kept beside the boolean. Collapsing "Behövs
    -- ej" and "Problem" into one FALSE is right for the visitor's question
    -- and wrong for every other question, so the distinction survives here.
    sign_status  TEXT, sign_note TEXT,
    parking_status TEXT, parking_note TEXT,

    n_sources    INTEGER,            -- rows in `sources` for this place
    n_images     INTEGER,
    uses_wikipedia INTEGER,          -- did the generated text draw on it
    built_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_f_score  ON features(score DESC);
CREATE INDEX IF NOT EXISTS idx_f_family ON features(family);
CREATE INDEX IF NOT EXISTS idx_f_lonlat ON features(lon, lat);
CREATE INDEX IF NOT EXISTS idx_f_sign   ON features(has_or_doesnt_need_sign);

CREATE TABLE IF NOT EXISTS images (
    image_id     INTEGER PRIMARY KEY,
    cluster_id   TEXT NOT NULL,
    uuid         TEXT,               -- the register row it was matched to
    -- Provenance, and it doubles as a confidence ordering.
    --   commons_wikidata  the image the Wikidata item itself designates
    --   commons_geo       a Commons file whose own coordinates fall nearby:
    --                     a good guess, still a guess
    --   county_pdf        extracted from a county folder, page-matched
    --   county_page       an <img> on a county visitor page
    source       TEXT NOT NULL,
    file         TEXT,               -- 'File:Bohus fastning 101.JPG'
    image_url    TEXT, thumb_url TEXT, page_url TEXT,
    local_path   TEXT,               -- set when we hold the bytes ourselves
    width        INTEGER, height INTEGER,
    distance_m   REAL,               -- only meaningful for commons_geo
    author       TEXT, credit TEXT,
    licence      TEXT, licence_url TEXT,
    -- Same discipline as `sources`: an image whose terms nobody has stated
    -- is stored and not shown. Reversible in that direction only.
    usable       INTEGER DEFAULT 1,
    fetched_at   TEXT
    -- The uniqueness rule is the index below, NOT a UNIQUE constraint on
    -- these columns. In SQL two NULLs are not equal, so a UNIQUE over
    -- (cluster_id, source, file, image_url) never matches a row whose
    -- image_url is NULL -- which is every image we hold as bytes rather
    -- than as a link. The Commons rows deduplicated correctly and the
    -- county-folder rows silently doubled on every rebuild: 56 became 112,
    -- and nothing errored.
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_i_identity ON images(
    cluster_id, source, COALESCE(file, ''), COALESCE(image_url, ''),
    COALESCE(local_path, ''));
CREATE INDEX IF NOT EXISTS idx_i_cluster ON images(cluster_id);
"""


def sign_state(status):
    """1 / 0 / None from a county's free-text sign or parking status.

    The vocabulary is a human's and the casing is inconsistent ("Finns OK",
    "Finns ok", "finns"), so match on a lowered prefix rather than equality.
    Anything unrecognised returns None -- an unreadable answer is not a no.
    """
    if not status:
        return None
    s = status.strip().lower()
    if s in ("-", ""):
        return None
    if s.startswith("finns") or s.startswith("behövs ej") \
            or s.startswith("behovs ej"):
        return 1
    if s.startswith("problem") or s.startswith("saknas"):
        return 0
    return None


def county_status():
    """cluster_id -> (sign, sign_note, parking, parking_note).

    The plan-to-cluster join is `crawl_lansstyrelsen.plan_clusters`, not a
    copy of it. The first version of this function did its own uuid-only
    lookup and resolved 68 places where the shared one resolves 156 -- the
    same bug, written twice, which is what having two implementations buys.

    A plan can name several register rows and so several clusters; each of
    them inherits the status, because the plan is about the maintained area
    they all sit in.
    """
    if not os.path.exists(paths.LANSSTYRELSEN):
        return {}
    l = sqlite3.connect(paths.ro(paths.LANSSTYRELSEN), uri=True)
    try:
        plans = l.execute("SELECT obj, sign, sign_note, parking, "
                          "parking_note FROM plans").fetchall()
    except sqlite3.OperationalError:
        return {}
    where = plan_clusters(l, paths.WORK)
    got = {}
    for obj, sign, snote, park, pnote in plans:
        for cid in where.get(obj, ()):
            got[cid] = (sign, snote, park, pnote)
    return got


def pdf_images(out):
    """Photographs lifted out of the county folders.

    Joined by lamningsnummer, which is the register's own designation, so
    these land on a cluster without any proximity guessing. Every one is
    stored with usable = 0: the folders declare no licence, and 36 of 117
    carry a photographer's name at all.
    """
    if not os.path.exists(paths.LANSSTYRELSEN):
        return 0
    l = sqlite3.connect(paths.ro(paths.LANSSTYRELSEN), uri=True)
    try:
        rows = l.execute("SELECT local_path, lamning, heading, credit, "
                         "dataset_id FROM pdf_images "
                         "WHERE lamning IS NOT NULL").fetchall()
    except sqlite3.OperationalError:
        return 0            # --images has not been run yet
    w = sqlite3.connect(paths.ro(paths.WORK), uri=True)
    by_lam = {}
    for lam, cid in w.execute("""
            SELECT s.lamningsnummer, sc.cluster_id FROM sites s
            JOIN site_clusters sc ON sc.uuid = s.uuid
            WHERE s.lamningsnummer IS NOT NULL"""):
        by_lam.setdefault(lam, set()).add(cid)
    n = 0
    for path, lam, heading, credit, ds_id in rows:
        county = ds_id.split(":")[1] if ":" in ds_id else None
        for cid in by_lam.get(lam, ()):
            out.execute("""
                INSERT OR IGNORE INTO images
                  (cluster_id, source, file, local_path, author, credit,
                   licence, usable, fetched_at)
                VALUES (?,?,?,?,?,?,?,0,datetime('now'))
            """, (cid, "county_pdf", os.path.basename(path), path, credit,
                  f"Länsstyrelsen ({county})" if county else None,
                  "unresolved"))
            n += 1
    out.commit()
    return n


def build_features(out):
    w = sqlite3.connect(paths.ro(paths.WORK), uri=True)
    status = county_status()
    print(f"{len(status):,} places carry a county sign/parking status")

    gen = {}
    if os.path.exists(paths.GENERATED):
        g = sqlite3.connect(paths.ro(paths.GENERATED), uri=True)
        for row in g.execute("SELECT cluster_id, title, content, title_en, "
                             "content_en FROM ai_descriptions"):
            gen[row[0]] = row[1:]
        print(f"{len(gen):,} generated descriptions "
              f"({sum(1 for v in gen.values() if v[3]):,} with English)")

    # The representative register row: what the app links to on Fornsök, and
    # the same choice build_clusters.py made for the pin, so the link and the
    # dot agree about which of the twenty graves is the one being shown.
    rep = dict(w.execute("""
        SELECT sc.cluster_id, s.uuid FROM site_clusters sc
        JOIN sites s ON s.uuid = sc.uuid
        GROUP BY sc.cluster_id
        HAVING s.description_len = MAX(s.description_len)"""))
    lam = dict(w.execute("SELECT uuid, lamningsnummer FROM sites"))
    url = dict(w.execute("SELECT uuid, url FROM sites"))

    n = 0
    for r in w.execute("""
            SELECT c.cluster_id, c.lon, c.lat, c.name, c.dominant_class,
                   c.n_sites, c.parish, c.municipality, c.county,
                   sc.score_full, sc.excluded_hard, sc.excluded_soft
            FROM clusters c
            LEFT JOIN scores sc ON sc.cluster_id = c.cluster_id"""):
        (cid, lon, lat, name, cls, n_sites, parish, muni, county,
         score, hard, soft) = r
        title, content, title_en, content_en = gen.get(cid,
                                                       (None,) * 4)
        sign, snote, park, pnote = status.get(cid, (None,) * 4)
        uuid = rep.get(cid)
        out.execute("""
            INSERT OR REPLACE INTO features
              (cluster_id, lon, lat, name, title, content, title_en,
               content_en, class_sv, family, n_sites, lamningsnummer,
               raa_url, parish, municipality, county, score, excluded,
               has_or_doesnt_need_sign, has_or_doesnt_need_parking,
               sign_status, sign_note, parking_status, parking_note,
               built_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                    datetime('now'))
        """, (cid, lon, lat, name, title, content, title_en, content_en,
              cls, FAMILY.get(cls, "misc"), n_sites, lam.get(uuid),
              url.get(uuid), parish, muni, county, score,
              1 if (hard or soft) else 0,
              sign_state(sign), sign_state(park),
              sign, snote, park, pnote))
        n += 1
    out.commit()
    return n


def build_images(out):
    """Commons photos, carried over with their licences intact."""
    if not os.path.exists(paths.WIKIMEDIA):
        return 0
    wm = sqlite3.connect(paths.ro(paths.WIKIMEDIA), uri=True)
    w = sqlite3.connect(paths.ro(paths.WORK), uri=True)
    cl = dict(w.execute("SELECT uuid, cluster_id FROM site_clusters"))
    n = 0
    for (uuid, f, src, dist, page, thumb, img, wd, ht, lic, lurl, author,
         credit, fetched) in wm.execute("""
            SELECT uuid, file, source, distance_m, page_url, thumb_url,
                   image_url, width, height, licence, licence_url, author,
                   credit, fetched_at FROM photos"""):
        cid = cl.get(uuid)
        if not cid:
            continue
        out.execute("""
            INSERT OR IGNORE INTO images
              (cluster_id, uuid, source, file, image_url, thumb_url,
               page_url, width, height, distance_m, author, credit,
               licence, licence_url, usable, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (cid, uuid, f"commons_{src}", f, img, thumb, page, wd, ht,
              dist, author, credit, lic, lurl, 1 if lic else 0, fetched))
        n += 1
    out.commit()
    return n


def rollups(out):
    """The counts on `features` that summarise the other two tables."""
    out.execute("""
        UPDATE features SET n_images = COALESCE((
            SELECT COUNT(*) FROM images i
             WHERE i.cluster_id = features.cluster_id), 0)""")
    try:
        out.execute("""
            UPDATE features SET n_sources = COALESCE((
                SELECT COUNT(*) FROM sources s
                 WHERE s.cluster_id = features.cluster_id), 0)""")
        out.execute("""
            UPDATE features SET uses_wikipedia = COALESCE((
                SELECT MAX(s.kind = 'wikipedia') FROM sources s
                 JOIN generation_sources g
                   ON g.source_id = s.source_id
                  AND g.cluster_id = s.cluster_id
                 WHERE s.cluster_id = features.cluster_id), 0)""")
    except sqlite3.OperationalError:
        # build_sources.py has not written into this file yet.
        pass
    out.commit()


def status(out):
    n, = out.execute("SELECT COUNT(*) FROM features").fetchone()
    print(f"\n{n:,} places")
    for label, q in (
            ("with a generated description", "content IS NOT NULL"),
            ("  also in English", "content_en IS NOT NULL"),
            ("with a folk name", "name IS NOT NULL"),
            ("with at least one image", "n_images > 0"),
            ("excluded from export", "excluded = 1")):
        c, = out.execute(f"SELECT COUNT(*) FROM features WHERE {q}").fetchone()
        print(f"  {c:>9,}  {label}")
    print("\n  sign / parking, where a county told us:")
    for col in ("has_or_doesnt_need_sign", "has_or_doesnt_need_parking"):
        rows = out.execute(f"SELECT {col}, COUNT(*) FROM features "
                           f"WHERE {col} IS NOT NULL GROUP BY 1").fetchall()
        got = {v: c for v, c in rows}
        print(f"    {col:28s} true {got.get(1,0):4d}   "
              f"false {got.get(0,0):4d}")
    print("\n  images by provenance:")
    for src, c, lic in out.execute("""
            SELECT source, COUNT(*), SUM(usable) FROM images
            GROUP BY 1 ORDER BY 2 DESC"""):
        print(f"    {c:>7,}  {src:20s} {lic or 0:,} usable")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=paths.PLACES)
    p.add_argument("--status", action="store_true")
    args = p.parse_args()

    out = sqlite3.connect(args.out)
    out.executescript(SCHEMA)
    out.commit()
    if args.status:
        status(out)
        return

    n = build_features(out)
    print(f"features: {n:,} rows")
    n = build_images(out)
    print(f"images:   {n:,} from Commons")
    n = pdf_images(out)
    print(f"          {n:,} from county folders")
    rollups(out)
    status(out)


if __name__ == "__main__":
    main()
