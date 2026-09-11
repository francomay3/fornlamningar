#!/usr/bin/env python3
"""
Stage 7: one table of everything anyone has written about a place.

Franco's design, and it is the right shape for what this project actually is.
The database is the product; the app is a view of it. So the thing that has to
be well built is not the prose we generate but the corpus we generate FROM --
and that corpus now comes from five or six places with different licences,
different reliability and different reasons to exist.

    register        The surveyor's entry. CC0, so we owe nobody anything.
                    Describes what is physically present, for an inventory.
    wikipedia       Lead paragraphs. CC BY-SA 4.0. Describes why the place
                    matters.
    county_pdf      A county board's visitor folder. Written for somebody
                    standing there with a map.
    county_attr     Description fields out of the counties' own geodata.
    county_page     Per-site visitor pages on lansstyrelsen.se. 119 distinct
                    ones -- NOT the ~1,100 a first count suggested, which was
                    counting rows: several objects link to the same page and
                    308 more point at an intranet host. Still the best prose
                    in the corpus.
    user_comment    Not yet. This is where it lands.
    sign_ocr        Not yet. Photographs of on-site signs, read by OCR --
                    text written by an antiquarian for a visitor standing in
                    front of the thing, which is the register we do not have.

THREE RULES the schema enforces rather than hopes for.

ONE ROW PER SOURCE, NEVER EDITED. A user comment does not modify a
description; it becomes another row. Generation then means: select every row
for a cluster, hand them to the model, keep the result. That is why a user
contribution can improve a place without anyone being able to overwrite what
the register said, and why regenerating later with a better model needs no
re-fetching.

ATTRIBUTION IS DERIVED, NOT DECLARED. `generation_sources` records which rows
went into a given generated text, so the credit line is computed from what was
actually used. A boolean like `uses_wikipedia` drifts the first time somebody
changes the prompt; a link table cannot.

LICENCE TRAVELS WITH THE ROW. Mixing CC0 and CC BY-SA is fine as long as it is
per row and tracked: a generated description drawing on a BY-SA row is an
adaptation and carries share-alike, and one drawing only on CC0 rows owes
nothing. That obligation is a property of the row set, so it is computed the
same way the credit line is.

Reads:  src/data/sites.sqlite, wikimedia.sqlite, lansstyrelsen.sqlite
Writes: src/data/sources.sqlite

Usage:
    python build_sources.py
    python build_sources.py --status
"""

import argparse
import json
import os
import sqlite3

SITES_DB = "src/data/sites.sqlite"
WIKI_DB = "src/data/wikimedia.sqlite"
LST_DB = "src/data/lansstyrelsen.sqlite"
OUT_DB = "src/data/sources.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id   INTEGER PRIMARY KEY,
    -- The cluster is the unit: it is what the app shows as one pin and what a
    -- visitor thinks of as one place. `uuid` narrows it to the exact register
    -- record when we know which one, and is NULL for anything said about the
    -- place as a whole.
    cluster_id  TEXT NOT NULL,
    uuid        TEXT,
    kind        TEXT NOT NULL,
    lang        TEXT,
    title       TEXT,
    text        TEXT NOT NULL,
    author      TEXT,
    publisher   TEXT,
    licence     TEXT,
    licence_url TEXT,
    url         TEXT,
    -- How much weight the generator should give this row. Not a confidence in
    -- the facts -- everything here is from a real publisher -- but in how
    -- well it answers "what will I see and why should I go".
    trust       REAL DEFAULT 0.5,
    -- Off for rows kept for provenance but not fed to the model: a licence we
    -- have not cleared, or a user comment awaiting moderation.
    usable      INTEGER DEFAULT 1,
    fetched_at  TEXT,
    UNIQUE (cluster_id, kind, lang, url, text)
);
CREATE INDEX IF NOT EXISTS idx_src_cluster ON sources(cluster_id);
CREATE INDEX IF NOT EXISTS idx_src_kind    ON sources(kind);

-- Which source rows produced a given generated description. The join table is
-- the attribution: see the module docstring.
CREATE TABLE IF NOT EXISTS generation_sources (
    cluster_id  TEXT NOT NULL,
    lang        TEXT NOT NULL,
    source_id   INTEGER NOT NULL,
    PRIMARY KEY (cluster_id, lang, source_id)
);
"""

# Trust, and the ordering is the argument. A visitor page was written to get
# somebody to the place; a survey entry was written to record that it exists.
TRUST = {
    "county_page": 1.0,
    "county_pdf": 1.0,
    "sign_ocr": 1.0,
    "wikipedia": 0.8,
    "county_attr": 0.6,
    "register": 0.5,
    "user_comment": 0.5,
}

CC0 = ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/")
BYSA4 = ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/")


def add(out, cluster_id, kind, text, **kw):
    if not cluster_id or not text or not str(text).strip():
        return 0
    out.execute("""
        INSERT OR IGNORE INTO sources
          (cluster_id, uuid, kind, lang, title, text, author, publisher,
           licence, licence_url, url, trust, usable, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
    """, (cluster_id, kw.get("uuid"), kind, kw.get("lang"), kw.get("title"),
          " ".join(str(text).split()), kw.get("author"), kw.get("publisher"),
          kw.get("licence"), kw.get("licence_url"), kw.get("url"),
          TRUST.get(kind, 0.5), kw.get("usable", 1)))
    return 1


def cluster_map(sites):
    return dict(sites.execute("SELECT uuid, cluster_id FROM site_clusters"))


def from_register(sites, out, cl):
    """The surveyor's own text, CC0.

    Only non-boilerplate entries: roughly a third of the register is a
    template sentence that says nothing, and feeding those to the model taught
    it to write template sentences back.
    """
    n = 0
    for uuid, text in sites.execute("""
            SELECT uuid, beskrivning FROM sites
            WHERE beskrivning IS NOT NULL AND beskrivning <> ''
              AND COALESCE(beskrivning_is_boilerplate, 0) = 0"""):
        n += add(out, cl.get(uuid), "register", text, uuid=uuid, lang="sv",
                 publisher="Riksantikvarieämbetet",
                 licence=CC0[0], licence_url=CC0[1],
                 url=f"https://app.raa.se/open/fornsok/lamning/{uuid}")
    return n


def from_wikipedia(out, cl):
    if not os.path.exists(WIKI_DB):
        return 0
    w = sqlite3.connect(f"file:{WIKI_DB}?mode=ro", uri=True)
    n = 0
    for uuid, lang, title, extract, url in w.execute(
            "SELECT uuid, lang, title, extract, url FROM wiki_articles "
            "WHERE extract IS NOT NULL AND extract <> ''"):
        n += add(out, cl.get(uuid), "wikipedia", extract, uuid=uuid,
                 lang=lang, title=title, publisher=f"Wikipedia ({lang})",
                 licence=BYSA4[0], licence_url=BYSA4[1], url=url)
    return n


def from_counties(out):
    """The county boards: folder blurbs and geodata description fields.

    Licence is recorded as unresolved rather than guessed. Swedish public
    authorities usually publish under terms that permit reuse with
    attribution, but "usually" is not a licence -- so these rows are stored
    with `usable = 0` until the actual terms are read. Storing them now and
    clearing them later is reversible; generating from them first is not.
    """
    if not os.path.exists(LST_DB):
        return 0, 0
    l = sqlite3.connect(f"file:{LST_DB}?mode=ro", uri=True)
    n_pdf = n_attr = 0

    for cluster_id, name, props, ds_title, county in l.execute("""
            SELECT DISTINCT m.cluster_id, o.name, o.props, d.title, d.county
            FROM matches m
            JOIN objects o ON o.dataset_id = m.dataset_id
                          AND o.obj_id = m.obj_id
            JOIN datasets d ON d.id = m.dataset_id
            WHERE m.how <> 'in_landscape' AND m.cluster_id IS NOT NULL"""):
        blob = json.loads(props) if props else {}
        if not isinstance(blob, dict):
            continue
        blurb = blob.get("blurb")
        if blurb and len(blurb) > 40:
            n_pdf += add(out, cluster_id, "county_pdf", blurb, lang="sv",
                         title=name, publisher=f"Länsstyrelsen ({county})",
                         licence="unresolved", usable=0)
            continue
        # Free-text fields out of the geodata, under whichever of the dozen
        # names the publisher chose.
        for key, val in blob.items():
            k = key.lower()
            if not isinstance(val, str) or len(val) < 60:
                continue
            if val.lower().startswith(("http", "\\\\", "/")):
                continue
            if k.startswith(("beskr", "kommentar", "anm", "referens")):
                n_attr += add(out, cluster_id, "county_attr", val, lang="sv",
                              title=name,
                              publisher=f"Länsstyrelsen ({county})",
                              licence="unresolved", usable=0)
    return n_pdf, n_attr


def from_county_pages(out):
    """Per-site visitor pages on lansstyrelsen.se.

    The best prose in the corpus, and the reason is what it was written for.
    The register records that a thing exists; these were written to get
    somebody to walk to it, so they talk about the climb, the view and the
    parking:

      "Gor en utflykt till jarnaldern! Blaxhult fornborg ... ligger pa toppen
       av ett berg och nas via branta stigar. Fran toppen har du en storslagen
       utsikt som beloning."

    A page can be linked from several county objects and therefore land on
    several clusters, which is correct: some of these pages describe an area
    with a handful of monuments in it, and each of them legitimately shares
    the text. The UNIQUE constraint on (cluster_id, kind, lang, url, text)
    keeps that from duplicating within a cluster.
    """
    if not os.path.exists(LST_DB):
        return 0
    l = sqlite3.connect(f"file:{LST_DB}?mode=ro", uri=True)
    try:
        rows = l.execute("""
            SELECT DISTINCT m.cluster_id, p.url, p.title, p.text, p.county
            FROM pages p
            JOIN page_objects po ON po.url = p.url
            JOIN matches m ON m.dataset_id = po.dataset_id
                          AND m.obj_id = po.obj_id
            WHERE p.text IS NOT NULL AND LENGTH(p.text) > 200
              AND m.how <> 'in_landscape' AND m.cluster_id IS NOT NULL
        """).fetchall()
    except sqlite3.OperationalError:
        return 0            # --pages has not been run yet
    n = 0
    for cluster_id, url, title, text, county in rows:
        n += add(out, cluster_id, "county_page", text, lang="sv", title=title,
                 publisher=f"Länsstyrelsen ({county})", url=url,
                 licence="unresolved", usable=0)
    return n


def status(out):
    print("sources by kind:")
    for kind, n, cl, use in out.execute("""
            SELECT kind, COUNT(*), COUNT(DISTINCT cluster_id), SUM(usable)
            FROM sources GROUP BY 1 ORDER BY 2 DESC"""):
        print(f"  {kind:14} {n:>7,} rows  {cl:>7,} clusters  "
              f"{int(use or 0):>7,} usable")
    tot, cl = out.execute("SELECT COUNT(*), COUNT(DISTINCT cluster_id) "
                          "FROM sources").fetchone()
    print(f"\n{tot:,} rows over {cl:,} clusters")
    print("\nclusters by how many INDEPENDENT kinds describe them:")
    for k, n in out.execute("""
            SELECT kinds, COUNT(*) FROM (
              SELECT cluster_id, COUNT(DISTINCT kind) AS kinds
              FROM sources GROUP BY cluster_id
            ) GROUP BY 1 ORDER BY 1 DESC"""):
        print(f"  {k} kind(s): {n:,} clusters")
    print("\nlicences:")
    for lic, n in out.execute("SELECT COALESCE(licence,'(none)'), COUNT(*) "
                              "FROM sources GROUP BY 1 ORDER BY 2 DESC"):
        print(f"  {lic:16} {n:>7,}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sites-db", default=SITES_DB)
    p.add_argument("--out", default=OUT_DB)
    p.add_argument("--status", action="store_true")
    args = p.parse_args()

    out = sqlite3.connect(args.out)
    out.executescript(SCHEMA)
    out.commit()

    if args.status:
        status(out)
        return

    sites = sqlite3.connect(f"file:{args.sites_db}?mode=ro", uri=True)
    cl = cluster_map(sites)
    print(f"{len(cl):,} sites mapped to clusters")

    n = from_register(sites, out, cl)
    out.commit()
    print(f"  register:    {n:,} rows offered")
    n = from_wikipedia(out, cl)
    out.commit()
    print(f"  wikipedia:   {n:,} rows offered")
    n_pdf, n_attr = from_counties(out)
    out.commit()
    print(f"  county_pdf:  {n_pdf:,} rows offered")
    print(f"  county_attr: {n_attr:,} rows offered")
    n = from_county_pages(out)
    out.commit()
    print(f"  county_page: {n:,} rows offered")
    print()
    status(out)


if __name__ == "__main__":
    main()
