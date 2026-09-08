#!/usr/bin/env python3
"""
Crawl the K-samsok API for every lamning UUID in the full GeoPackage and store
the raw JSON responses, unparsed, in their own SQLite database.

The only goal here is to get the network stage done once so that all later
parsing work can happen offline. Responses are stored verbatim.

Usage:
    python crawl_ksamsok.py --seed          # populate the target list, then stop
    python crawl_ksamsok.py                 # crawl (resumes automatically)
    python crawl_ksamsok.py --limit 200     # crawl only 200 pending targets
    python crawl_ksamsok.py --status        # progress report, no network calls

Safe to interrupt with Ctrl-C at any point: in-flight requests are drained,
the current batch is committed, and the next run picks up where this one left off.
"""

import argparse
import json
import os
import queue
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Optional

GPKG_PATH = "src/data/fornlamningar_full.gpkg"
RAW_DB_PATH = "src/data/ksamsok_raw.sqlite"
API_BASE = "https://kulturarvsdata.se/raa/lamning"
USER_AGENT = "Fornlamningar-Crawler/1.0 (+https://github.com/francomay3/fornlamningar)"

# Response bodies are stored zlib-compressed; level 6 gets ~5.3x on this JSON-LD
# for negligible CPU next to a 75 ms round trip.
ZLIB_LEVEL = 6

GPKG_LAYERS = (
    "PS_NationalMonuments_point",
    "PS_NationalMonuments_line",
    "PS_NationalMonuments_poly",
)

# HTTP statuses where the resource genuinely is not there. Recorded once and
# never retried, so a re-run does not keep hammering known-dead UUIDs.
TERMINAL_STATUSES = {400, 401, 403, 404, 410}


# --------------------------------------------------------------------------- #
# database
# --------------------------------------------------------------------------- #

def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=60.0)
    # WAL keeps the file readable (and intact) while the crawl is writing, and
    # survives a hard kill without corrupting the database.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def encode_raw(body: str) -> bytes:
    """Compress a response body for storage."""
    return zlib.compress(body.encode("utf-8"), ZLIB_LEVEL)


def decode_raw(blob, compression: str = "zlib") -> Optional[str]:
    """Inverse of encode_raw. Tolerates legacy uncompressed TEXT rows."""
    if blob is None:
        return None
    if compression == "none":
        return blob if isinstance(blob, str) else blob.decode("utf-8")
    return zlib.decompress(blob).decode("utf-8")


def load_response(conn: sqlite3.Connection, uuid: str) -> Optional[dict]:
    """Fetch one stored response from the database and parse it."""
    row = conn.execute(
        "SELECT raw_json, compression FROM responses WHERE uuid = ?", (uuid,)
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return json.loads(decode_raw(row[0], row[1]))


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Bring a pre-compression database up to the current schema."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(responses)")}
    if not cols or "compression" in cols:
        return

    print("Migrating responses table to compressed storage...")
    conn.execute("ALTER TABLE responses ADD COLUMN compression TEXT NOT NULL DEFAULT 'none'")
    if "stored_size" not in cols:
        conn.execute("ALTER TABLE responses ADD COLUMN stored_size INTEGER")
    conn.commit()

    rows = conn.execute(
        "SELECT uuid, raw_json FROM responses "
        "WHERE raw_json IS NOT NULL AND compression = 'none'"
    ).fetchall()
    with conn:
        for uuid, raw in rows:
            body = raw if isinstance(raw, str) else raw.decode("utf-8")
            blob = encode_raw(body)
            conn.execute(
                "UPDATE responses SET raw_json = ?, compression = 'zlib', "
                "byte_size = ?, stored_size = ? WHERE uuid = ?",
                (blob, len(body.encode("utf-8")), len(blob), uuid),
            )
    conn.execute("UPDATE responses SET compression = 'zlib' WHERE raw_json IS NULL")
    conn.commit()
    print(f"  recompressed {len(rows):,} existing rows")
    conn.execute("VACUUM")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS targets (
            uuid       TEXT PRIMARY KEY,
            inspireid  TEXT,
            layer      TEXT,
            attempts   INTEGER NOT NULL DEFAULT 0,
            last_error TEXT
        );

        -- raw_json holds the response body exactly as received, zlib-compressed
        -- (about 5x smaller). Use decode_raw() / --dump to read it back.
        CREATE TABLE IF NOT EXISTS responses (
            uuid        TEXT PRIMARY KEY,
            http_status INTEGER NOT NULL,
            raw_json    BLOB,
            compression TEXT NOT NULL DEFAULT 'zlib',
            fetched_at  TEXT NOT NULL,
            elapsed_ms  INTEGER,
            byte_size   INTEGER,
            stored_size INTEGER
        );

        CREATE TABLE IF NOT EXISTS crawl_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            ended_at   TEXT,
            fetched    INTEGER DEFAULT 0,
            failed     INTEGER DEFAULT 0,
            note       TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_targets_attempts ON targets(attempts);
        CREATE INDEX IF NOT EXISTS idx_responses_status ON responses(http_status);
        """
    )
    conn.commit()


def seed_targets(conn: sqlite3.Connection, gpkg_path: str) -> int:
    """Pull every distinct UUID out of the GeoPackage into the target list.

    The UUID is not a column: it is the last path segment of
    legalfoundationdocument (https://pub.raa.se/visa/objekt/lamning/<uuid>).
    """
    if not os.path.exists(gpkg_path):
        sys.exit(f"GeoPackage not found: {gpkg_path}")

    src = sqlite3.connect(f"file:{gpkg_path}?mode=ro", uri=True)
    rows: dict[str, tuple[str, str]] = {}
    for layer in GPKG_LAYERS:
        try:
            cur = src.execute(
                f'SELECT inspireid, legalfoundationdocument FROM "{layer}" '
                "WHERE legalfoundationdocument IS NOT NULL"
            )
        except sqlite3.OperationalError as exc:
            print(f"  ! skipping layer {layer}: {exc}")
            continue
        n = 0
        for inspireid, doc in cur:
            uuid = doc.rstrip("/").rsplit("/", 1)[-1]
            # Cheap sanity check; keeps malformed URLs out of the queue.
            if len(uuid) == 36 and uuid.count("-") == 4:
                rows.setdefault(uuid, (inspireid, layer))
                n += 1
        print(f"  {layer}: {n} rows with a UUID")
    src.close()

    conn.executemany(
        "INSERT OR IGNORE INTO targets (uuid, inspireid, layer) VALUES (?, ?, ?)",
        [(u, i, l) for u, (i, l) in rows.items()],
    )
    conn.commit()
    print(f"  {len(rows)} distinct UUIDs across all layers")
    return len(rows)


def pending_uuids(conn: sqlite3.Connection, max_attempts: int, limit: Optional[int]):
    sql = """
        SELECT t.uuid FROM targets t
        LEFT JOIN responses r ON r.uuid = t.uuid
        WHERE r.uuid IS NULL AND t.attempts < ?
        ORDER BY t.attempts ASC, t.rowid ASC
    """
    params: list = [max_attempts]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [row[0] for row in conn.execute(sql, params)]


# --------------------------------------------------------------------------- #
# rate limiting
# --------------------------------------------------------------------------- #

class RateLimiter:
    """Token bucket shared by all workers. Caps requests per second globally."""

    def __init__(self, rps: float):
        self.interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = threading.Lock()
        self._next = time.monotonic()

    def acquire(self) -> None:
        if not self.interval:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            if wait <= 0:
                self._next = now + self.interval
                wait = 0.0
            else:
                self._next += self.interval
        if wait > 0:
            time.sleep(wait)


# --------------------------------------------------------------------------- #
# fetching
# --------------------------------------------------------------------------- #

@dataclass
class Result:
    uuid: str
    status: int
    raw: Optional[str]
    elapsed_ms: int
    error: Optional[str]
    retryable: bool


def fetch_one(uuid: str, timeout: float) -> Result:
    url = f"{API_BASE}/{uuid}"
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            elapsed = int((time.monotonic() - start) * 1000)
            # Validate before storing so a truncated or HTML error page never
            # lands in the database pretending to be a response.
            try:
                json.loads(body)
            except json.JSONDecodeError as exc:
                return Result(uuid, resp.status, None, elapsed,
                              f"invalid JSON: {exc}", True)
            return Result(uuid, resp.status, body, elapsed, None, False)

    except urllib.error.HTTPError as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        retryable = exc.code not in TERMINAL_STATUSES
        return Result(uuid, exc.code, None, elapsed, f"HTTP {exc.code}", retryable)

    except Exception as exc:  # timeouts, DNS, connection resets
        elapsed = int((time.monotonic() - start) * 1000)
        return Result(uuid, 0, None, elapsed, f"{type(exc).__name__}: {exc}", True)


# --------------------------------------------------------------------------- #
# crawl
# --------------------------------------------------------------------------- #

stop_event = threading.Event()


def crawl(conn, uuids, workers, rps, timeout, batch_size):
    limiter = RateLimiter(rps)
    work: queue.Queue = queue.Queue()
    results: queue.Queue = queue.Queue()
    for u in uuids:
        work.put(u)

    def worker():
        while not stop_event.is_set():
            try:
                uuid = work.get_nowait()
            except queue.Empty:
                return
            limiter.acquire()
            if stop_event.is_set():
                return
            results.put(fetch_one(uuid, timeout))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()

    total = len(uuids)
    ok = failed = terminal = done = 0
    pending_rows: list[Result] = []
    started = time.monotonic()
    last_report = 0.0

    def flush():
        """Single writer, batched. One transaction per batch."""
        if not pending_rows:
            return
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO responses "
                "(uuid, http_status, raw_json, compression, fetched_at, "
                " elapsed_ms, byte_size, stored_size) "
                "VALUES (?, ?, ?, 'zlib', ?, ?, ?, ?)",
                [
                    (r.uuid, r.status,
                     encode_raw(r.raw) if r.raw else None,
                     time.strftime("%Y-%m-%dT%H:%M:%S"), r.elapsed_ms,
                     len(r.raw.encode("utf-8")) if r.raw else 0,
                     len(encode_raw(r.raw)) if r.raw else 0)
                    for r in pending_rows if not r.retryable
                ],
            )
            conn.executemany(
                "UPDATE targets SET attempts = attempts + 1, last_error = ? "
                "WHERE uuid = ?",
                [(r.error, r.uuid) for r in pending_rows],
            )
        pending_rows.clear()

    while done < total:
        if stop_event.is_set() and results.empty():
            break
        try:
            r = results.get(timeout=0.5)
        except queue.Empty:
            if not any(t.is_alive() for t in threads):
                break
            continue

        done += 1
        pending_rows.append(r)
        if r.raw is not None:
            ok += 1
        elif r.retryable:
            failed += 1
        else:
            terminal += 1

        if len(pending_rows) >= batch_size:
            flush()

        now = time.monotonic()
        if now - last_report > 0.5:
            rate = done / max(now - started, 0.001)
            eta = (total - done) / rate if rate > 0 else 0
            sys.stderr.write(
                f"\r  {done}/{total}  ok={ok} retry={failed} dead={terminal}  "
                f"{rate:.1f}/s  eta {eta/60:.0f}m   "
            )
            sys.stderr.flush()
            last_report = now

    flush()
    sys.stderr.write("\n")

    if stop_event.is_set():
        # Drop anything still queued; those UUIDs stay pending for next run.
        while not work.empty():
            try:
                work.get_nowait()
            except queue.Empty:
                break

    return ok, failed, terminal


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #

def report(conn) -> None:
    t = conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0]
    r = conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
    good = conn.execute(
        "SELECT COUNT(*) FROM responses WHERE raw_json IS NOT NULL"
    ).fetchone()[0]
    dead = r - good
    stuck = conn.execute(
        "SELECT COUNT(*) FROM targets t LEFT JOIN responses r ON r.uuid = t.uuid "
        "WHERE r.uuid IS NULL AND t.attempts > 0"
    ).fetchone()[0]
    sizes = conn.execute(
        "SELECT COALESCE(SUM(byte_size), 0), COALESCE(SUM(stored_size), 0) "
        "FROM responses WHERE raw_json IS NOT NULL"
    ).fetchone()
    size = os.path.getsize(RAW_DB_PATH) / 1e6 if os.path.exists(RAW_DB_PATH) else 0

    print(f"  targets       {t:>9,}")
    print(f"  stored        {r:>9,}  ({good:,} with JSON, {dead:,} dead)")
    print(f"  remaining     {t - r:>9,}  ({stuck:,} previously errored)")
    print(f"  database      {size:>9.1f} MB")
    if t:
        print(f"  progress      {100.0 * r / t:>8.1f}%")
    if sizes[1]:
        ratio = sizes[0] / sizes[1]
        print(f"  response data {sizes[1]/1e6:>9.1f} MB stored "
              f"({sizes[0]/1e6:.1f} MB raw, {ratio:.1f}x)")
        if good:
            per = sizes[1] / good
            print(f"  projected     {per * t / 1e9:>9.2f} GB at completion")
    for status, n in conn.execute(
        "SELECT http_status, COUNT(*) FROM responses GROUP BY 1 ORDER BY 2 DESC"
    ):
        print(f"    HTTP {status}: {n:,}")


# --------------------------------------------------------------------------- #

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seed", action="store_true", help="seed target list and exit")
    p.add_argument("--status", action="store_true", help="show progress and exit")
    p.add_argument("--limit", type=int, help="crawl at most N pending targets")
    p.add_argument("--workers", type=int, default=6, help="concurrent requests (default 6)")
    p.add_argument("--rps", type=float, default=8.0, help="global requests/sec cap (default 8)")
    p.add_argument("--timeout", type=float, default=30.0, help="per-request timeout seconds")
    p.add_argument("--batch", type=int, default=100, help="rows per commit (default 100)")
    p.add_argument("--max-attempts", type=int, default=3,
                   help="give up on a UUID after N failed attempts (default 3)")
    p.add_argument("--retry-failed", action="store_true",
                   help="reset attempt counters so exhausted UUIDs are retried")
    p.add_argument("--dump", metavar="UUID",
                   help="print one stored response as JSON and exit")
    p.add_argument("--gpkg", default=GPKG_PATH)
    p.add_argument("--db", default=RAW_DB_PATH)
    args = p.parse_args()

    conn = connect(args.db)
    init_schema(conn)
    migrate_schema(conn)

    if args.dump:
        data = load_response(conn, args.dump)
        if data is None:
            sys.exit(f"No stored response for {args.dump}")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    if args.status:
        report(conn)
        return

    if conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0] == 0:
        print("Seeding target list from GeoPackage...")
        seed_targets(conn, args.gpkg)
    elif args.seed:
        print("Target list already seeded; re-scanning for new UUIDs...")
        seed_targets(conn, args.gpkg)

    if args.seed:
        report(conn)
        return

    if args.retry_failed:
        n = conn.execute(
            "UPDATE targets SET attempts = 0, last_error = NULL WHERE attempts > 0 "
            "AND uuid NOT IN (SELECT uuid FROM responses)"
        ).rowcount
        conn.commit()
        print(f"Reset {n:,} exhausted targets for retry.")

    todo = pending_uuids(conn, args.max_attempts, args.limit)
    if not todo:
        print("Nothing pending. Crawl is complete.")
        report(conn)
        return

    signal.signal(signal.SIGINT, lambda *_: (
        stop_event.set(),
        sys.stderr.write("\n  interrupt received, draining in-flight requests...\n"),
    ))

    log_id = conn.execute(
        "INSERT INTO crawl_log (started_at, note) VALUES (?, ?)",
        (time.strftime("%Y-%m-%dT%H:%M:%S"), f"{len(todo)} pending"),
    ).lastrowid
    conn.commit()

    print(f"Crawling {len(todo):,} UUIDs "
          f"({args.workers} workers, {args.rps}/s cap)")
    t0 = time.monotonic()
    ok, failed, terminal = crawl(
        conn, todo, args.workers, args.rps, args.timeout, args.batch
    )
    elapsed = time.monotonic() - t0

    with conn:
        conn.execute(
            "UPDATE crawl_log SET ended_at = ?, fetched = ?, failed = ? WHERE id = ?",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), ok, failed + terminal, log_id),
        )

    print(f"\nDone in {elapsed/60:.1f}m: {ok:,} stored, "
          f"{terminal:,} dead, {failed:,} retryable")
    report(conn)
    if stop_event.is_set():
        print("\nInterrupted. Re-run the same command to resume.")
        sys.exit(130)


if __name__ == "__main__":
    main()
