"""Write the sources behind a release's descriptions, for fl_sources.

    python3 export_sources.py                   # releases/latest -> /tmp
    python3 export_sources.py --release 11 --out /tmp/fl_sources.jsonl.gz

One JSON object per line, one line per (published uuid, source row). The
loader is in the web repo -- ../franco-may/scripts/load-fl-sources.cjs --
because that is where the database credential lives; this side only reads.

WHICH PLACES: the ones in the release's Swedish descriptions, not every
cluster in places.sqlite. The table exists so a moderator can see why a
published text says what it says, and a place nobody can open has no text
to explain.

WHICH UUID: the one the release published. A description is keyed by a
member uuid and the sources by cluster, and the representative in
`features` is not always the member the release used -- joining on it
finds under half of them. `feature_sites` holds every member, so that is
the join.

The release directory is only read. It is immutable, and this is not part
of it: the output goes wherever --out says, /tmp by default.
"""
import argparse
import gzip
import json
import os
import sqlite3

import paths

HERE = os.path.dirname(os.path.abspath(__file__))
RELEASES = os.path.join(HERE, "src", "data", "releases")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default="latest")
    ap.add_argument("--out", default="/tmp/fl_sources.jsonl.gz")
    args = ap.parse_args()

    rel = os.path.realpath(os.path.join(RELEASES, args.release))
    generation = int(os.path.basename(rel))
    desc = os.path.join(rel, "descriptions.sv.db")

    db = sqlite3.connect(f"file:{paths.PLACES}?mode=ro", uri=True)
    db.execute(f"ATTACH 'file:{desc}?mode=ro' AS d")
    rows = db.execute("""
        SELECT x.uuid, s.source_id, s.cluster_id, s.kind, s.lang, s.title,
               s.text, s.author, s.publisher, s.licence, s.licence_url, s.url,
               s.trust, s.fetched_at,
               EXISTS (SELECT 1 FROM generation_sources g
                        WHERE g.cluster_id = s.cluster_id AND g.lang = 'sv'
                          AND g.source_id = s.source_id) AS used
          FROM d.descriptions x
          JOIN feature_sites fs ON fs.uuid = x.uuid
          JOIN sources s ON s.cluster_id = fs.cluster_id
         WHERE s.usable = 1 AND s.text <> ''
         ORDER BY x.uuid, s.trust DESC, s.source_id
    """)
    keys = ["place_uuid", "source_id", "cluster_id", "kind", "lang", "title",
            "body", "author", "publisher", "licence", "licence_url", "url",
            "trust", "fetched_at", "used"]
    n = 0
    places = set()
    with gzip.open(args.out, "wt", encoding="utf-8") as out:
        for r in rows:
            row = dict(zip(keys, r))
            row["used"] = bool(row["used"])
            row["generation"] = generation
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
            places.add(row["place_uuid"])
    print(f"generation {generation}: {n} sources for {len(places)} places "
          f"-> {args.out} ({os.path.getsize(args.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
