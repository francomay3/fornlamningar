#!/usr/bin/env python3
"""Take Franco's remaining comments off the sheet and keep the text as a source.

Every comment still showing is his (the Google import he re-tagged as his own
on 2026-09-18). Withdrawing is a `comment_delete` with
`reason: "investigation"`. The phone hides the comment. `build_sources.py`
reads that reason and stores the body as kind `investigation`, not as a
visitor comment. A comment already withdrawn because it described the wrong
remain has no reason, and does not come back.

Ratings and "been here" are left as they are.

    python convert_comments.py            # how many
    python convert_comments.py --apply    # write the deletes, then the sources

Safe to run again: a comment already withdrawn is not withdrawn twice.
"""

import argparse
import json
import sqlite3

import paths
from apply_comment_fixes import mirror, write
from build_sources import cluster_map, from_contributions
from crawl_contributions import database_url

CHUNK = 200


def surviving(conn):
    gone = set()
    for (payload,) in conn.execute(
            "SELECT payload FROM events WHERE kind = 'comment_delete'"):
        target = json.loads(payload).get("target_event_id")
        if target:
            gone.add(target)
    rows = []
    for r in conn.execute("""
            SELECT event_id, place_uuid, author
              FROM events
             WHERE kind = 'comment'
               AND json_extract(payload, '$.source') IS NULL
             ORDER BY seq
            """):
        if r[0] not in gone:
            rows.append({
                "kind": "comment_delete",
                "place_uuid": r[1],
                "author": r[2],
                "payload": {"target_event_id": r[0], "reason": "investigation"},
            })
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    conn = sqlite3.connect(paths.ro(paths.CONTRIBUTIONS), uri=True)
    batch = surviving(conn)
    conn.close()
    print(f"{len(batch)} comments still on the sheet")
    if not args.apply or not batch:
        if args.apply:
            print("nothing to withdraw")
        else:
            return
    else:
        url = database_url()
        written = 0
        last = None
        for i in range(0, len(batch), CHUNK):
            rows = write(url, batch[i:i + CHUNK])
            mirror(rows)
            written += len(rows)
            last = rows[-1]["seq"]
            print(f"  withdrew {written}, seq through {last}", flush=True)
        print(f"wrote {written} comment_delete events, seq through {last}")

    sites = sqlite3.connect(f"file:{paths.WORK}?mode=ro", uri=True)
    out = sqlite3.connect(paths.PLACES)
    n_user, n_inv = from_contributions(out, cluster_map(sites))
    out.commit()
    usable = out.execute(
        "SELECT kind, COUNT(*), SUM(usable) FROM sources "
        "WHERE kind IN ('user_comment', 'investigation') GROUP BY 1"
    ).fetchall()
    out.close()
    print(f"sources offered: user_comment {n_user}, investigation {n_inv}")
    for kind, n, use in usable:
        print(f"  {kind}: {n} rows, {int(use or 0)} usable")


if __name__ == "__main__":
    main()
