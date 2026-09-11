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
    -- The class this place WEARS, from its representative member.
    class_sv     TEXT,
    family       TEXT,               -- families.py id, not a label
    -- What is actually in it: "Hög×3; Stensättning×2". A cluster is a place,
    -- but it is not one thing, and 5,159 of 13,729 multi-class clusters mix
    -- more than one FAMILY -- a fort and a hollow way at the same
    -- coordinate. Every representative-choice bug in this pipeline came
    -- from making the cluster win an internal election it should never have
    -- had to hold, so the mix travels with it and a sheet can say both.
    class_mix    TEXT,
    n_sites      INTEGER,            -- register rows inside this place
    n_classes    INTEGER,
    uuid         TEXT,               -- representative member, explicitly
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

    -- WHEN, for every kind of content, because the maintenance question is
    -- never "what do we have" but "what has gone out of date".
    --
    -- The pair that matters is description_generated_at against
    -- sources_newest_at: if a source arrived after the text was written,
    -- the text has not seen it. That is `stale`, and it is derived here
    -- rather than asked at query time so it appears in an export and in the
    -- app without anyone re-deriving the rule.
    --
    -- These are the CONTENT timestamps, not the build timestamp. `built_at`
    -- is when this row was assembled and is nearly useless for deciding
    -- anything -- it is now on every rebuild.
    description_generated_at  TEXT,
    description_model         TEXT,
    description_translated_at TEXT,
    -- Newest CONTENT date among this place's sources.
    sources_newest_at         TEXT,
    -- Newest date at which a source row APPEARED. This is the one `stale`
    -- compares against: a field we only started parsing yesterday is new to
    -- us even though the API published it last week.
    sources_first_seen_at     TEXT,
    images_newest_at          TEXT,
    stale                     INTEGER,
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

-- Every register record inside a place, not only the one it wears.
--
-- This is the table that makes "identity is a set" real rather than a
-- comment. The Fornsök link can list the members instead of picking one,
-- and the 19,881 clusters whose representative was ambiguous stop needing
-- a winner at all -- the ambiguity was never in the data, it was in
-- insisting on a single answer.
CREATE TABLE IF NOT EXISTS feature_sites (
    cluster_id  TEXT NOT NULL,
    uuid        TEXT NOT NULL,
    class_sv    TEXT,
    lamningsnummer TEXT,
    raa_url     TEXT,
    is_representative INTEGER DEFAULT 0,
    PRIMARY KEY (cluster_id, uuid)
);
CREATE INDEX IF NOT EXISTS idx_fs_cluster ON feature_sites(cluster_id);
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
    these land on a cluster without any proximity guessing.

    Stored usable, with the photographer where the folder names one (36 of
    117) and the county as publisher otherwise. The folders declare no
    licence; using them anyway is Franco's call, and attribution is what
    keeps the worst case at "somebody asks and we remove it".
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
                VALUES (?,?,?,?,?,?,?,1,datetime('now'))
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
                             "content_en, created_at, model, translated_at "
                             "FROM ai_descriptions"):
            gen[row[0]] = row[1:]
        print(f"{len(gen):,} generated descriptions "
              f"({sum(1 for v in gen.values() if v[3]):,} with English)")

    # The representative register row: what the app links to on Fornsök.
    #
    # Read from clusters.rep_uuid, which build_clusters.py decides once. This
    # used to be its own GROUP BY / HAVING MAX(description_len), missing the
    # "excluded classes lose first" clause and with no deterministic
    # tie-break -- so for 19,881 of 40,656 multi-site clusters it named a
    # different member than the tile did, and the "Visa i Fornsök" button
    # would have opened a monument other than the one described.
    rep = dict(w.execute(
        "SELECT cluster_id, rep_uuid FROM clusters "
        "WHERE rep_uuid IS NOT NULL"))
    lam = dict(w.execute("SELECT uuid, lamningsnummer FROM sites"))
    url = dict(w.execute("SELECT uuid, url FROM sites"))

    n = 0
    for r in w.execute("""
            SELECT c.cluster_id, c.lon, c.lat, c.name, c.dominant_class,
                   c.n_sites, c.parish, c.municipality, c.county,
                   c.class_mix, c.n_classes,
                   sc.score_full, sc.excluded_hard, sc.excluded_soft
            FROM clusters c
            LEFT JOIN scores sc ON sc.cluster_id = c.cluster_id"""):
        (cid, lon, lat, name, cls, n_sites, parish, muni, county,
         class_mix, n_classes, score, hard, soft) = r
        (title, content, title_en, content_en, made_at, model,
         translated_at) = gen.get(cid, (None,) * 7)
        sign, snote, park, pnote = status.get(cid, (None,) * 4)
        uuid = rep.get(cid)
        out.execute("""
            INSERT OR REPLACE INTO features
              (cluster_id, lon, lat, name, title, content, title_en,
               content_en, class_sv, family, class_mix, n_sites, n_classes,
               uuid, lamningsnummer,
               raa_url, parish, municipality, county, score, excluded,
               has_or_doesnt_need_sign, has_or_doesnt_need_parking,
               sign_status, sign_note, parking_status, parking_note,
               description_generated_at, description_model,
               description_translated_at, built_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                    ?,?,datetime('now'))
        """, (cid, lon, lat, name, title, content, title_en, content_en,
              cls, FAMILY.get(cls, "misc"), class_mix, n_sites, n_classes,
              uuid, lam.get(uuid),
              url.get(uuid), parish, muni, county, score,
              1 if (hard or soft) else 0,
              sign_state(sign), sign_state(park),
              sign, snote, park, pnote, made_at, model, translated_at))
        n += 1
    out.commit()
    return n


def build_members(out):
    """One row per register record inside each place."""
    w = sqlite3.connect(paths.ro(paths.WORK), uri=True)
    rep = dict(w.execute("SELECT cluster_id, rep_uuid FROM clusters"))
    n = 0
    for cid, uuid, cls, lam, url in w.execute("""
            SELECT sc.cluster_id, s.uuid, s.class_sv, s.lamningsnummer, s.url
            FROM site_clusters sc JOIN sites s ON s.uuid = sc.uuid"""):
        out.execute("""
            INSERT OR REPLACE INTO feature_sites
              (cluster_id, uuid, class_sv, lamningsnummer, raa_url,
               is_representative)
            VALUES (?,?,?,?,?,?)
        """, (cid, uuid, cls, lam, url, 1 if rep.get(cid) == uuid else 0))
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
    """The counts and dates on `features` that summarise the other tables."""
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

    out.execute("""
        UPDATE features SET images_newest_at = (
            SELECT MAX(i.fetched_at) FROM images i
             WHERE i.cluster_id = features.cluster_id)""")
    try:
        out.execute("""
            UPDATE features SET sources_newest_at = (
                SELECT MAX(s.fetched_at) FROM sources s
                 WHERE s.cluster_id = features.cluster_id)""")
    except sqlite3.OperationalError:
        pass
    try:
        out.execute("""
            UPDATE features SET sources_first_seen_at = (
                SELECT MAX(s.first_seen_at) FROM sources s
                 WHERE s.cluster_id = features.cluster_id)""")
    except sqlite3.OperationalError:
        pass
    # A description is stale when a source row APPEARED after it was written
    # -- not when the content was published. Using fetched_at here missed
    # every one of the 679 places whose tradition we had held in an unparsed
    # JSON field since before the text was generated.
    # NULL, not 0, where there is no description: "not stale" would claim the
    # text is current when there is no text.
    out.execute("""
        UPDATE features SET stale = CASE
            WHEN description_generated_at IS NULL THEN NULL
            WHEN sources_first_seen_at IS NULL THEN 0
            WHEN sources_first_seen_at > description_generated_at THEN 1
            ELSE 0 END""")
    out.commit()


def status(out):
    n, = out.execute("SELECT COUNT(*) FROM features").fetchone()
    print(f"\n{n:,} places")
    for label, q in (
            ("with a generated description", "content IS NOT NULL"),
            ("  also in English", "content_en IS NOT NULL"),
            ("with a folk name", "name IS NOT NULL"),
            ("with at least one image", "n_images > 0"),
            ("excluded from export", "excluded = 1"),
            ("stale: a source is newer than the text", "stale = 1")):
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
    n = build_members(out)
    print(f"members:  {n:,} register records")
    n = build_images(out)
    print(f"images:   {n:,} from Commons")
    n = pdf_images(out)
    print(f"          {n:,} from county folders")
    rollups(out)
    status(out)


if __name__ == "__main__":
    main()
