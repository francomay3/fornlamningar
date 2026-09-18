#!/usr/bin/env python3
"""Stage 0f: mirror the app's contribution log into the pipeline.

`fl_events` in franco-may's Postgres is the only input to this pipeline that
is not a public dataset: it is what people who used the app told us. Every
other crawler here re-fetches an upstream that will still be there tomorrow;
this one reads a log that only grows, so it pulls by CURSOR and never asks
for the same event twice.

WHY A CURSOR AND NOT A TIMESTAMP. The server stamps every event with a
monotonic `seq` taken inside the inserting transaction, precisely so that
`seq > since` cannot skip a row -- see the long note in
franco-may/scripts/fornlamningar-events.sql about why a bigserial would.
Paginating by time instead would inherit the phone's clock, which is the
user's and may be wrong. We store the highest seq we have seen and ask for
more than that.

GAPS IN seq ARE EXPECTED. A resend consumes a number without inserting a
row, so `max(seq)` is not `count(*)` and never will be. That is documented
upstream and is not a sign of loss.

WHY SQL OVER HTTP AND NOT psycopg. Port 5432 is accepted and then reset on
some networks -- a corporate security agent, a sandbox -- and the symptom is
ECONNRESET that reads exactly like a dead database. franco-may/lib/db.ts
carries the same note and points at its own schema script, which uses Neon's
HTTPS endpoint for this reason. This is a crawler: it has to work from
wherever it is run, not from one network.

WHAT THIS DOES NOT DO. It does not interpret anything. `build_labels.py`
turns these rows into labels, and that split is the same one every other
stage here keeps: acquisition is expensive and happens once, derivation is
cheap and happens many times. Re-deciding what a three-star rating means
must never require asking the server again.

Reads:  DATABASE_URL (franco-may/.env.local), Neon SQL-over-HTTP
Writes: src/data/contributions.sqlite  (tables `events`, `sync`)

Usage:
    python crawl_contributions.py
    python crawl_contributions.py --from 0     # re-read the whole log
    python crawl_contributions.py --status
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY,   -- the server's number, not ours
    event_id   TEXT NOT NULL UNIQUE,
    kind       TEXT NOT NULL,
    place_uuid TEXT NOT NULL,
    author     TEXT NOT NULL,
    payload    TEXT NOT NULL,         -- JSON, kept verbatim
    client_ts  TEXT,
    server_ts  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ev_place ON events(place_uuid, kind);
CREATE INDEX IF NOT EXISTS idx_ev_kind  ON events(kind);
CREATE INDEX IF NOT EXISTS idx_ev_author ON events(author);

-- One row. `cursor` is the highest seq pulled; `at` is when, for the log.
CREATE TABLE IF NOT EXISTS sync (
    id     INTEGER PRIMARY KEY CHECK (id = 1),
    cursor INTEGER NOT NULL,
    at     TEXT
);
INSERT OR IGNORE INTO sync (id, cursor, at) VALUES (1, 0, NULL);
"""

WEB_ENV = os.path.expanduser("~/projects/franco-may/.env.local")


def database_url():
    """DATABASE_URL, from the environment or from franco-may's .env.local.

    Not duplicated into this repo's own env on purpose: two copies of one
    credential is two places to rotate and one to forget.
    """
    u = os.environ.get("DATABASE_URL")
    if u:
        return u
    if not os.path.exists(WEB_ENV):
        sys.exit(f"no DATABASE_URL and no {WEB_ENV}")
    m = re.search(r"^DATABASE_URL=(.+)$", open(WEB_ENV).read(), re.M)
    if not m:
        sys.exit(f"no DATABASE_URL in {WEB_ENV}")
    return m.group(1).strip().strip('"').strip("'")


def query(url, sql, params=None):
    endpoint = f"https://{urllib.parse.urlparse(url).hostname}/sql"
    body = json.dumps({"query": sql, "params": params or []}).encode()
    req = urllib.request.Request(endpoint, data=body, headers={
        "Content-Type": "application/json",
        "Neon-Connection-String": url,
        # Raw text, so a bigint comes back as a string instead of losing
        # precision through a JSON double. `seq` is a BIGINT.
        "Neon-Raw-Text-Output": "true",
    })
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())["rows"]
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from Neon: {e.read().decode()[:300]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="since", type=int,
                    help="ignore the stored cursor and start here")
    ap.add_argument("--page", type=int, default=2000)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()

    os.makedirs(paths.DATA, exist_ok=True)
    conn = sqlite3.connect(paths.CONTRIBUTIONS)
    conn.executescript(SCHEMA)
    conn.commit()

    cur = conn.execute("SELECT cursor, at FROM sync WHERE id=1").fetchone()
    if a.status:
        n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        print(f"{paths.CONTRIBUTIONS}: {n:,} events, cursor {cur[0]}, "
              f"last pull {cur[1] or 'never'}")
        for k, c, p in conn.execute(
                "SELECT kind, COUNT(*), COUNT(DISTINCT place_uuid) "
                "FROM events GROUP BY kind ORDER BY 2 DESC"):
            print(f"  {k:14s} {c:>7,}  {p:>6,} places")
        return

    since = cur[0] if a.since is None else a.since
    url = database_url()
    print(f"pulling fl_events with seq > {since}")
    total = 0
    while True:
        rows = query(url, """
            SELECT seq, event_id, kind, place_uuid, author,
                   payload::text AS payload,
                   client_ts::text AS client_ts, server_ts::text AS server_ts
            FROM fl_events WHERE seq > $1 ORDER BY seq LIMIT $2
        """, [str(since), a.page])
        if not rows:
            break
        with conn:
            # OR REPLACE, not OR IGNORE. The log is append-only by design, so
            # IGNORE is the right instinct -- and it is wrong the one time a
            # row is edited server-side, because the mirror then keeps a copy
            # of a payload that no longer exists anywhere else and nothing
            # ever corrects it. REPLACE costs nothing on rows that did not
            # change and makes `--from 0` a real repair rather than a no-op.
            conn.executemany(
                "INSERT OR REPLACE INTO events "
                "(seq,event_id,kind,place_uuid,author,payload,client_ts,server_ts) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [(int(r["seq"]), r["event_id"], r["kind"], r["place_uuid"],
                  r["author"], r["payload"], r["client_ts"], r["server_ts"])
                 for r in rows])
        since = int(rows[-1]["seq"])
        total += len(rows)
        print(f"  +{len(rows)} (seq now {since})", flush=True)
        # The cursor moves only after the rows are committed, so a crash
        # re-reads a page instead of skipping one. INSERT OR IGNORE makes the
        # re-read free.
        with conn:
            conn.execute("UPDATE sync SET cursor=?, at=datetime('now') "
                         "WHERE id=1", (since,))
        if len(rows) < a.page:
            break
    n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"pulled {total:,} new; {n:,} events on disk, cursor {since}")


if __name__ == "__main__":
    main()
