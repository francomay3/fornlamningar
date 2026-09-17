#!/usr/bin/env python3
"""Upload the register's places to the service's Postgres, as `fl_places`.

    python3 upload_places.py --local          # the docker-compose Postgres
    python3 upload_places.py --remote         # Neon, from franco-may/.env.local

WHY THE SERVER NEEDS THIS. The phone carries the top 10,000 by score inside
vector tiles, and the one question those cannot answer is the one that matters
most for labelling: "I am standing in front of something -- which of the
register's places is it?" By construction the answer is usually a place the
score left out, which is exactly what the tiles do not contain. See section 9
of TODO.md.

DROP AND RELOAD, NOT A DIFF, and that is a statement about what this data is.
A description is a function of one place's own sources, so a change to one
place is a change to one row and a delta is the right shape. A score is
computed over the whole set: re-run the scoring and every row's percentile
moves, so there is no such thing as "the rows that changed". The honest
operation is "replace the snapshot", and a generation number tells readers
which snapshot they are looking at.

VIA A STAGING TABLE, so that no reader ever sees a half-loaded map. COPY into
`fl_places_load`, then one transaction that swaps it into place. The load is
the slow part and it happens where nobody is looking; the visible part is a
rename.

THROUGH psql RATHER THAN A POSTGRES DRIVER, for the same reason build_tiles.py
shells out to tippecanoe: this pipeline is deliberately near-stdlib, and psql
is already on the machine that has a Postgres to talk to. `\\copy ... FROM
STDIN` streams, so 126k rows never exist in memory on either side, and it is
about two orders of magnitude faster than a row-at-a-time INSERT.
"""

import argparse
import os
import re
import shutil
import sqlite3
import subprocess
import sys

import paths
from families import FAMILY

LOCAL_URL = "postgres://fornkoll:fornkoll@127.0.0.1:15432/fornkoll"
ENV_LOCAL = os.path.expanduser("~/projects/franco-may/.env.local")

# The same default the app's export uses. `build_tiles.py --top` defaults to
# None (the whole country); the 10,000 is an explicit argument there, so it is
# an explicit default here too rather than a number inherited by accident.
TOP = 10_000


def remote_url():
    """DATABASE_URL out of the service repo's .env.local.

    Read rather than asked for, because the connection string is a secret
    that belongs in that file and nowhere else -- including not in this
    repo's environment, and not in a terminal's history.
    """
    if not os.path.exists(ENV_LOCAL):
        sys.exit(f"no {ENV_LOCAL} - run `vercel env pull .env.local` there")
    for line in open(ENV_LOCAL, encoding="utf-8"):
        if line.startswith("DATABASE_URL="):
            return line[len("DATABASE_URL="):].strip().strip('"')
    sys.exit(f"no DATABASE_URL in {ENV_LOCAL}")


def one_line(text, limit=140):
    """The first sentence-ish of the register's text, for the picker list."""
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0] + "\u2026"
    return t


def rows(db, top):
    """Every place the pipeline did not exclude outright, ranked as the tiles rank it.

    THE ORDER BY IS build_tiles.py's, copied deliberately and knowingly. The
    only thing `in_tiles` means is "this one made that cut", so the two
    queries have to agree; if they drift, the flag lies in the most confusing
    possible direction -- the app offers a place as missing when it is already
    a pin under the user's thumb. build_tiles.py has a comment about three
    copies of a rule that came to disagree, and this is a fourth. It is here
    rather than imported because that script is a __main__ with a tippecanoe
    dependency; if a third copy ever appears, that is the moment to move the
    query into a module both import.

    THE SOFT-EXCLUDED ARE IN, and they are most of the point: 37,626 places
    whose score was not good enough for the map. A human standing in front of
    one of those is the single most informative label this project can get,
    because unlike a visit the app suggested, it has no selection bias.

    The hard-excluded are out, all 87,328: classes that are not places (a
    legal boundary), the buried ones with nothing above ground, and records
    the register itself struck off. Those are not places with a poor
    prognosis -- offering them in a "which of these are you looking at" list
    would be the same noise that was just taken off the map.
    """
    conn = sqlite3.connect(paths.ro(db), uri=True)
    conn.row_factory = sqlite3.Row
    out = conn.execute("""
        SELECT c.cluster_id, c.lon, c.lat, c.name, c.dominant_class,
               c.n_sites, c.best_description,
               sc.score_intrinsic AS score,
               sc.excluded_soft
        FROM clusters c
        JOIN scores sc ON sc.cluster_id = c.cluster_id
        WHERE c.lon IS NOT NULL
          AND sc.excluded_hard = 0
        ORDER BY sc.score_intrinsic DESC
    """).fetchall()
    conn.close()

    # `title` comes from places.sqlite, which is a different file and holds
    # rows from previous clusterings too -- 251,029 features against the
    # clusters that exist now. Looked up by id, so the stale ones simply do
    # not match.
    p = sqlite3.connect(paths.ro(paths.PLACES), uri=True)
    titles = dict(p.execute("SELECT cluster_id, title FROM features"))
    p.close()

    # in_tiles is rank among the non-soft-excluded, which is what --top
    # counts over there.
    rank = 0
    for r in out:
        in_tiles = False
        if not r["excluded_soft"]:
            rank += 1
            in_tiles = rank <= top
        yield {
            "cluster_id": r["cluster_id"],
            "lon": r["lon"],
            "lat": r["lat"],
            "family": FAMILY.get(r["dominant_class"] or "", "misc"),
            "class_sv": r["dominant_class"] or "",
            "name": r["name"] or "",
            "title": titles.get(r["cluster_id"]) or "",
            "blurb": one_line(r["best_description"]),
            "n_sites": r["n_sites"] or 1,
            "score": r["score"],
            "in_tiles": "t" if in_tiles else "f",
        }


COLUMNS = ["cluster_id", "lon", "lat", "family", "class_sv", "name", "title",
           "blurb", "n_sites", "score", "in_tiles", "generation"]


def tsv(rs):
    """Tab-separated, with the escapes COPY's text format defines.

    A tab or a newline inside a field would otherwise end the field or the
    row, and `best_description` is free text straight out of the register --
    it has both. NULL is not used at all: the query above substitutes empty
    strings, so a missing name and an empty name are the same thing here and
    the reader has one case fewer to handle.
    """
    def esc(v):
        if v is None:
            return "\\N"
        return (str(v).replace("\\", "\\\\").replace("\t", "\\t")
                .replace("\n", "\\n").replace("\r", "\\r"))
    cols = [c for c in COLUMNS if c != "generation"]
    for r in rs:
        yield "\t".join(esc(r[c]) for c in cols) + "\n"


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--local", action="store_true")
    g.add_argument("--remote", action="store_true",
                   help="Neon. This replaces what every phone reads.")
    ap.add_argument("--db", default=paths.WORK)
    ap.add_argument("--top", type=int, default=TOP,
                    help="how many the tiles carry, for the in_tiles flag")
    args = ap.parse_args()

    if not shutil.which("psql"):
        sys.exit("psql not found (brew install libpq, or postgresql)")
    url = LOCAL_URL if args.local else remote_url()

    # generation is stamped by the DEFAULT below, not carried per row.
    cols = ",".join(c for c in COLUMNS if c != "generation")

    # ONE TRANSACTION AROUND THE WHOLE THING, load included. The first version
    # of this loaded first and then stamped the generation with an UPDATE over
    # every row -- which in Postgres REWRITES every row, so a 24 MB table
    # arrived on disk as 96 MB of heap and needed a VACUUM FULL to give it
    # back. Deciding the number first and letting a column DEFAULT carry it
    # costs nothing and writes each row once.
    #
    # It also makes the swap stricter than it was: a reader either sees the
    # old snapshot or the new one, and `places_generation` is never a number
    # whose rows are still arriving. \copy inside a transaction is ordinary;
    # ON_ERROR_STOP turns any failure into a rollback of the lot.
    #
    # CREATE TABLE ... LIKE copies the columns and the defaults but NOT the
    # primary key or the index, which is the point: COPY into a table with no
    # index is much faster, and both are rebuilt after the rename.
    before = f"""
\\set ON_ERROR_STOP on
BEGIN;
DROP TABLE IF EXISTS fl_places_load;
CREATE TABLE fl_places_load (LIKE fl_places INCLUDING DEFAULTS);
UPDATE fl_config SET value = (value::int + 1)::text
 WHERE key = 'places_generation';
SELECT format('ALTER TABLE fl_places_load ALTER COLUMN generation SET DEFAULT %s', value)
  FROM fl_config WHERE key = 'places_generation' \\gexec
\\copy fl_places_load ({cols}) FROM STDIN
"""

    after = """
DROP TABLE fl_places;
ALTER TABLE fl_places_load RENAME TO fl_places;
ALTER TABLE fl_places ADD PRIMARY KEY (cluster_id);
CREATE INDEX fl_places_latlon ON fl_places (lat, lon);
COMMIT;
ANALYZE fl_places;
SELECT (SELECT value FROM fl_config WHERE key = 'places_generation')
         AS generation,
       count(*) AS rows,
       count(*) FILTER (WHERE in_tiles) AS in_tiles,
       pg_size_pretty(pg_total_relation_size('fl_places')) AS size
  FROM fl_places;
"""

    proc = subprocess.Popen(["psql", url, "-v", "ON_ERROR_STOP=1", "-f", "-"],
                            stdin=subprocess.PIPE, text=True)
    n = 0
    try:
        proc.stdin.write(before)
        for line in tsv(rows(args.db, args.top)):
            proc.stdin.write(line)
            n += 1
        # The lone backslash-dot that ends a COPY stream. Without it psql
        # reads the rest of the script as data.
        proc.stdin.write("\\.\n")
        proc.stdin.write(after)
        proc.stdin.close()
    except BrokenPipeError:
        sys.exit("psql closed the connection - see its error above")
    if proc.wait() != 0:
        sys.exit(f"psql exited {proc.returncode}")
    print(f"{n:,} places uploaded ({'local' if args.local else 'REMOTE'})")


if __name__ == "__main__":
    main()
