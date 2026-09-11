#!/usr/bin/env python3
"""
Stage 0e: pull the Wikidata layer and turn it into a label set.

Wikidata links to K-samsok through P1260 ("Swedish Open Cultural Heritage URI"),
whose value is the bare string `raa/lamning/<uuid>`. That gives an EXACT UUID
join -- the only non-spatial join available to this project.

Two things matter, and they are not the same thing:

  * 145,102 items carry P1260. Presence is worthless as a signal: 143,051 of
    them have zero sitelinks and are a bulk FMIS import.
  * ~2,048 have at least one Wikipedia article. Those are the label set, and the
    sitelink count grades them.

Caveat baked into the docs, not the data: 83% of the labelled set is
`Runristning`, because Swedish Wikipedia catalogues runestones systematically.
Fit with runestones excluded or you will build a runestone detector.

Reads:  Wikidata Query Service
Writes: src/data/sites.sqlite  (tables `wikidata`, `labels`)
Cache:  src/data/wikidata_cache/*.json  (delete to force a refetch)

Usage:
    python build_labels.py
    python build_labels.py --refresh        # ignore the cache
    python build_labels.py --skip-stubs     # only fetch items with sitelinks
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

import paths

DB = paths.WORK
CACHE_DIR = "src/data/wikidata_cache"
ENDPOINT = "https://query.wikidata.org/sparql"
UA = "Fornlamningar-Pipeline/1.0 (https://github.com/francomay3/fornlamningar)"

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)

# Items with at least one sitelink: the actual label set, with the graded count.
Q_LABELS = """
SELECT ?v ?item ?sitelinks ?sv ?en ?commons WHERE {
  ?item wdt:P1260 ?v .
  FILTER(STRSTARTS(STR(?v), "raa/lamning/"))
  ?item wikibase:sitelinks ?sitelinks .
  FILTER(?sitelinks > 0)
  OPTIONAL { ?sv   schema:about ?item ; schema:isPartOf <https://sv.wikipedia.org/> }
  OPTIONAL { ?en   schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }
  OPTIONAL { ?item wdt:P373 ?commons }
}
"""

# Items with a photograph (P18). A photo is proof somebody physically stood
# there, and 1,339 of these have NO Wikipedia article -- exactly the
# locally-known-but-undocumented population the sitelink labels are blind to.
Q_IMAGES = """
SELECT ?v ?item ?sitelinks ?img WHERE {
  ?item wdt:P1260 ?v .
  FILTER(STRSTARTS(STR(?v), "raa/lamning/"))
  ?item wdt:P18 ?img .
  ?item wikibase:sitelinks ?sitelinks .
}
"""

# Every P1260 lamning item, sitelinks included. Large; presence alone is not a
# signal, but the QID is the key for later Commons / image lookups.
Q_ALL = """
SELECT ?v ?item ?sitelinks WHERE {
  ?item wdt:P1260 ?v .
  FILTER(STRSTARTS(STR(?v), "raa/lamning/"))
  ?item wikibase:sitelinks ?sitelinks .
}
"""


def sparql(query: str, cache_name: str, refresh: bool, timeout: int = 600):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, cache_name)
    if os.path.exists(path) and not refresh:
        print(f"  using cached {path}")
        with open(path) as f:
            return json.load(f)

    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query})
    req = urllib.request.Request(
        url, headers={"Accept": "application/sparql-results+json", "User-Agent": UA}
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    n = len(data["results"]["bindings"])
    print(f"  fetched {n:,} rows in {time.time()-t0:.0f}s")
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def rows_of(data):
    """Yield (uuid, qid, sitelinks, sv, en, commons) with the UUID extracted.

    P1260 values are bare strings like `raa/lamning/<uuid>`, and SOME carry an
    `html/` infix (`raa/lamning/html/<uuid>`). A path split silently drops those,
    so match the UUID with a regex instead.
    """
    for b in data["results"]["bindings"]:
        raw = b["v"]["value"]
        m = UUID_RE.search(raw)
        if not m:
            continue
        yield (
            m.group(0),
            b["item"]["value"].rsplit("/", 1)[-1],
            int(b["sitelinks"]["value"]),
            b.get("sv", {}).get("value"),
            b.get("en", {}).get("value"),
            b.get("commons", {}).get("value"),
        )


SCHEMA = """
DROP TABLE IF EXISTS wikidata;
DROP TABLE IF EXISTS labels;

CREATE TABLE wikidata (
    uuid       TEXT PRIMARY KEY,
    qid        TEXT,
    sitelinks  INTEGER,
    sv_wiki    TEXT,
    en_wiki    TEXT,
    commons_category TEXT,
    image      TEXT,
    fetched_at TEXT
);

-- One row per labelled example. `source` and `confidence` keep the weak
-- (automatic) labels separate from any hand-labelled test set added later.
CREATE TABLE labels (
    uuid       TEXT NOT NULL,
    source     TEXT NOT NULL,
    -- Graded interest in [0,1]: 1 = signposted / clearly worth the trip,
    -- 0.5 = something visible but modest, 0 = nothing to see. Kept SEPARATE
    -- from `weight`, which is confidence in the observation. Conflating the two
    -- is what let sitelink counts masquerade as label confidence.
    label      REAL NOT NULL,
    weight     REAL,               -- graded strength, e.g. sitelink count
    confidence TEXT,               -- 'weak' | 'hand'
    note       TEXT,
    PRIMARY KEY (uuid, source)
);
"""

INDEXES = """
CREATE INDEX idx_wd_sitelinks ON wikidata(sitelinks);
CREATE INDEX idx_wd_qid       ON wikidata(qid);
CREATE INDEX idx_wd_image     ON wikidata(image);
CREATE INDEX idx_lab_source   ON labels(source);
CREATE INDEX idx_lab_label    ON labels(label);
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB)
    p.add_argument("--refresh", action="store_true", help="ignore the cache")
    p.add_argument("--skip-stubs", action="store_true",
                   help="skip the 145k-row query; fetch only items with sitelinks")
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"{args.db} not found -- run build_sites.py first")

    print("Fetching labelled items (sitelinks > 0)...")
    labels_data = sparql(Q_LABELS, "labels.json", args.refresh)
    labelled = {}
    for uuid, qid, sl, sv, en, commons in rows_of(labels_data):
        prev = labelled.get(uuid)
        if prev is None or sl > prev[1]:
            labelled[uuid] = (qid, sl, sv, en, commons)
    print(f"  {len(labelled):,} distinct UUIDs with >=1 sitelink")

    everything = dict(labelled)
    if not args.skip_stubs:
        print("Fetching all P1260 lamning items (large)...")
        try:
            all_data = sparql(Q_ALL, "all.json", args.refresh)
            n_new = 0
            for uuid, qid, sl, *_ in rows_of(all_data):
                if uuid not in everything:
                    everything[uuid] = (qid, sl, None, None, None)
                    n_new += 1
            print(f"  +{n_new:,} zero-sitelink stubs (kept for their QID only)")
        except Exception as exc:
            print(f"  ! stub query failed ({exc}); continuing with labels only")

    print("Fetching items with a photograph (P18)...")
    images = {}
    try:
        img_data = sparql(Q_IMAGES, "images.json", args.refresh)
        for b in img_data["results"]["bindings"]:
            m = UUID_RE.search(b["v"]["value"])
            if not m:
                continue
            images[m.group(0)] = (
                b["img"]["value"], int(b["sitelinks"]["value"]),
                b["item"]["value"].rsplit("/", 1)[-1],
            )
        no_article = sum(1 for _, (i, sl, q) in images.items() if sl == 0)
        print(f"  {len(images):,} with an image; {no_article:,} of them have no article")
    except Exception as exc:
        print(f"  ! image query failed ({exc}); continuing without it")

    for uuid, (img, sl, qid) in images.items():
        if uuid not in everything:
            everything[uuid] = (qid, sl, None, None, None)

    conn = sqlite3.connect(args.db)
    conn.executescript(SCHEMA)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO wikidata "
            "(uuid,qid,sitelinks,sv_wiki,en_wiki,commons_category,image,fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(u, q, s, sv, en, c,
              images.get(u, (None,))[0], now)
             for u, (q, s, sv, en, c) in everything.items()],
        )
        # Positives: a real Wikipedia article, graded by sitelink count.
        conn.executemany(
            "INSERT OR REPLACE INTO labels "
            "(uuid,source,label,weight,confidence,note) VALUES (?,?,?,?,?,?)",
            # weight is CONFIDENCE IN THE LABEL, not strength of notability.
            # It used to hold the sitelink count, which meant a 32-sitelink
            # runestone counted as 32 labels once the scorer started summing
            # weights -- reviving the very runestone dominance the fitting is
            # meant to avoid. The count stays in `note`, where it is harmless.
            [(u, "wikidata_sitelinks", 1, 1.0, "weak",
              f"{s} sitelink(s)") for u, (q, s, *_ ) in labelled.items()],
        )
        # Independent positive source: somebody photographed it. Weight 1.0 --
        # a photo is binary evidence, unlike the graded sitelink count.
        conn.executemany(
            "INSERT OR REPLACE INTO labels "
            "(uuid,source,label,weight,confidence,note) VALUES (?,?,?,?,?,?)",
            [(u, "wikidata_image", 1.0, 1.0, "weak",
              "has photograph" + ("" if sl else ", no article"))
             for u, (img, sl, qid) in images.items()],
        )
    # Hand-verified labels. Kept separate via confidence='hand' so they can act
    # as a test set that the weak labels never contaminate.
    hand_path = "hand_labels.csv"
    if os.path.exists(hand_path):
        import csv
        n_hand = 0
        with open(hand_path) as f:
            reader = csv.reader(l for l in f if l.strip() and not l.startswith("#"))
            pairs = []
            # Accepted formats, so older 3-column rows keep working:
            #   lamn,label,note
            #   lamn,label,certainty,note      certainty in 1..3
            # Certainty becomes the label `weight`: Street View is rarely
            # conclusive, so a hunch must not count as much as a clear look.
            CERT_WEIGHT = {1: 0.33, 2: 0.66, 3: 1.0}
            for row in reader:
                if len(row) < 2:
                    continue
                lamn, label = row[0].strip(), float(row[1])
                cert, note = 2, None
                if len(row) == 3:
                    note = row[2]
                elif len(row) >= 4:
                    try:
                        cert = int(row[2])
                    except ValueError:
                        cert = 2
                    note = row[3]
                cert = cert if cert in CERT_WEIGHT else 2
                w = CERT_WEIGHT[cert]
                for (uuid,) in conn.execute(
                        "SELECT uuid FROM sites WHERE lamningsnummer = ?", (lamn,)):
                    pairs.append((uuid, "hand", label, w, "hand",
                                  f"[certainty {cert}] {note or ''}".strip()))
                    n_hand += 1
        if pairs:
            with conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO labels "
                    "(uuid,source,label,weight,confidence,note) VALUES (?,?,?,?,?,?)",
                    pairs)
        print(f"hand labels loaded: {n_hand} matched to crawled sites")

    # County board recommendations, from crawl_lansstyrelsen.py.
    #
    # Nine or ten of the 21 county administrative boards publish the
    # fornlamningar they maintain and signpost, and Halland states the
    # selection criterion outright: accessible information by sign or online,
    # and reasonably accessible to visit. That is this project's target
    # variable, written by the authority.
    #
    # Weight follows how the match was made, because the routes are not
    # equally certain:
    #
    #   lamningsnummer  1.00  our primary key, published in the folder
    #   number          0.80  parsed RAA designation; over-generates across a
    #                         number group (Arsunda 9 holds five records)
    #   contains        0.66  inside a maintenance polygon under 1 km2
    #   geometry        0.50  nearest site within 150 m of a centroid
    #
    # `in_landscape` is deliberately NOT loaded. It means the site sits in a
    # designated cultural landscape, which can be 17,000 km2 wide -- a real
    # signal, but not a recommendation, and pooling it here would drown the
    # rest.
    #
    # Cross-checked against the hand labels before being trusted: of Franco's
    # 29 hand-labelled positives, 6 are independently on a county list, and of
    # his 11 negatives, ZERO are. Two independent judgements with no conflict.
    COUNTY_WEIGHT = {"lamningsnummer": 1.0, "number": 0.8,
                     "contains": 0.66, "geometry": 0.5}
    lst_path = "src/data/lansstyrelsen.sqlite"
    if os.path.exists(lst_path):
        lst = sqlite3.connect(f"file:{lst_path}?mode=ro", uri=True)
        best = {}
        for uuid, how in lst.execute(
                "SELECT uuid, how FROM matches WHERE how <> 'in_landscape'"):
            w = COUNTY_WEIGHT.get(how, 0.5)
            if w > best.get(uuid, 0):
                best[uuid] = w
        rows = [(u, "county", 1.0, w, "weak",
                 "recommended by a county administrative board")
                for u, w in best.items()]
        if rows:
            with conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO labels "
                    "(uuid,source,label,weight,confidence,note) "
                    "VALUES (?,?,?,?,?,?)", rows)
            print(f"county labels loaded: {len(rows):,} sites "
                  f"recommended by a county board")

    conn.executescript(INDEXES)
    conn.commit()

    # Report against the parsed sites table.
    q = conn.execute
    n_wd = q("SELECT COUNT(*) FROM wikidata").fetchone()[0]
    n_lab = q("SELECT COUNT(*) FROM labels WHERE label=1").fetchone()[0]
    joined = q("SELECT COUNT(*) FROM labels l JOIN sites s ON s.uuid=l.uuid").fetchone()[0]
    print(f"\nwikidata rows      {n_wd:>8,}")
    print(f"positive labels    {n_lab:>8,}")
    print(f"  joined to sites  {joined:>8,}  (rest not yet crawled or deprecated)")
    print("\ntop classes among positives:")
    for cls, n, tot in q("""
        SELECT s.class_sv, COUNT(*) n, SUM(l.weight) w
        FROM labels l JOIN sites s ON s.uuid=l.uuid
        WHERE l.label=1 GROUP BY 1 ORDER BY n DESC LIMIT 6
    """):
        print(f"  {str(cls)[:34]:<36}{n:>6,}  total sitelinks {int(tot or 0):>6,}")
    conn.close()


if __name__ == "__main__":
    main()
