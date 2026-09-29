#!/usr/bin/env python3
"""
Inscriptions from Samnordisk runtextdatabas, edition 2020.

The Uppsala page still offers a Windows program last packed in 2018. The
edition Runor serves is this API, and each Swedish record carries the RAÄ
uuid, so the join is exact.

Two things are kept. A record marked extant=false is a stone that is gone,
and build_scores drops a place only when every member is gone. A record that
still exists contributes its normalised reading and its English translation
as sources. Nothing else in the record is copied.

    python3 crawl_rundata.py
    python3 crawl_rundata.py --status
    python3 crawl_rundata.py --apply
"""

import argparse
import json
import sqlite3
import threading
import time
import urllib.request
from queue import Empty, Queue

import paths

API = "http://runor.nordiska.uu.se/rest"
UA = "Fornlamningar/1.0 (franco.may@etraveligroup.com)"
EDITION = "2020"

SCHEMA = """
CREATE TABLE IF NOT EXISTS checked (
    inscription_id TEXT PRIMARY KEY,
    error          TEXT,
    checked_at     TEXT
);
CREATE TABLE IF NOT EXISTS inscriptions (
    inscription_id TEXT PRIMARY KEY,
    signum         TEXT,
    extant         INTEGER,
    artefact       TEXT,
    period_sv      TEXT,
    uuid           TEXT,
    uri            TEXT,
    text_sv        TEXT,
    text_en        TEXT,
    fetched_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_ins_uuid ON inscriptions(uuid);
"""


def fetch(url, timeout):
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def kmr_uuid(body):
    for block in body.get("her_identifiers") or []:
        for ident in block.get("identifiers") or []:
            if ident.get("key") == "kmrId" and ident.get("value"):
                return ident["value"]
    return None


def readings(body):
    """Normalised runic Swedish, and the English translation."""
    sv = en = None
    for block in body.get("runic_texts") or []:
        for tr in block.get("translations") or []:
            lang = ((tr.get("language") or {}).get("language_code") or "")
            if lang.startswith("en") and tr.get("translation") and not en:
                en = tr["translation"].strip()
        for interp in block.get("interpretations") or []:
            lang = ((interp.get("language") or {}).get("language_code") or "")
            text = (interp.get("text") or "").strip()
            if not text:
                continue
            if lang == "RSV":
                sv = text
            elif not sv and not lang.startswith("en"):
                sv = text
    return sv, en


def row_of(body):
    uuid = kmr_uuid(body)
    if not uuid:
        return None
    signum1 = (body.get("signum1") or "").strip()
    signum2 = (body.get("signum2") or "").strip()
    signum = f"{signum1} {signum2}".strip() or None
    extant = body.get("extant")
    if extant is True:
        extant = 1
    elif extant is False:
        extant = 0
    else:
        extant = None
    sv, en = readings(body)
    period = body.get("period") or {}
    return {
        "inscription_id": body["inscription_id"],
        "signum": signum,
        "extant": extant,
        "artefact": body.get("artefact"),
        "period_sv": period.get("sv"),
        "uuid": uuid,
        "uri": body.get("uri"),
        "text_sv": sv,
        "text_en": en,
    }


class Limiter:
    def __init__(self, rps):
        self.interval = 1.0 / rps if rps else 0
        self._lock = threading.Lock()
        self._next = time.monotonic()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def inscription_ids(timeout):
    signa = fetch(f"{API}/signa?matching_text=&edition_id={EDITION}", timeout)
    ids = []
    seen = set()
    for s in signa:
        for i in s.get("inscriptions") or []:
            if i not in seen:
                seen.add(i)
                ids.append(i)
    return ids


def apply():
    """Drop gone places and add the translations. Idempotent."""
    import build_scores
    import build_sources

    work = sqlite3.connect(paths.WORK)
    lost = build_scores.lost_runestone_clusters(work)
    work.executemany(
        "UPDATE scores SET excluded_hard = 1 WHERE cluster_id = ?",
        [(c,) for c in lost])
    work.commit()
    places = sqlite3.connect(paths.PLACES)
    places.executemany(
        "UPDATE features SET excluded = 1 WHERE cluster_id = ?",
        [(c,) for c in lost])
    sites = sqlite3.connect(paths.ro(paths.WORK), uri=True)
    n = build_sources.from_rundata(places, build_sources.cluster_map(sites))
    places.commit()
    print(f"excluded {len(lost):,} places whose stone is gone")
    print(f"offered {n:,} inscription sources")
    return lost


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--status", action="store_true")
    p.add_argument("--apply", action="store_true",
                   help="exclude gone stones and write sources, no fetching")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--rps", type=float, default=12)
    p.add_argument("--timeout", type=float, default=40)
    args = p.parse_args()

    out = sqlite3.connect(paths.RUNDATA)
    out.executescript(SCHEMA)
    out.commit()
    if args.status:
        n, linked, gone, with_text = out.execute("""
            SELECT COUNT(*),
                   SUM(uuid IS NOT NULL),
                   SUM(extant = 0),
                   SUM(extant = 1 AND (COALESCE(text_en,'') <> ''
                                    OR COALESCE(text_sv,'') <> ''))
            FROM inscriptions""").fetchone()
        checked, = out.execute("SELECT COUNT(*) FROM checked").fetchone()
        print(f"checked {checked:,}   linked {linked or 0:,}   "
              f"gone {gone or 0:,}   with text {with_text or 0:,}   "
              f"rows {n:,}")
        return
    if args.apply:
        apply()
        return

    done = {r[0] for r in out.execute(
        "SELECT inscription_id FROM checked WHERE error IS NULL")}
    ids = inscription_ids(args.timeout)
    todo = [i for i in ids if i not in done]
    print(f"{len(todo):,} inscriptions to read, {len(done):,} already done, "
          f"{len(ids):,} in edition {EDITION}", flush=True)
    if not todo:
        apply()
        return

    limiter = Limiter(args.rps)
    work = Queue()
    for i in todo:
        work.put(i)
    results = Queue()
    stop = threading.Event()

    def worker():
        while not stop.is_set():
            try:
                iid = work.get_nowait()
            except Empty:
                return
            limiter.wait()
            try:
                body = fetch(
                    f"{API}/inscriptions/{iid}?edition_id={EDITION}",
                    args.timeout)
                results.put((iid, row_of(body), None))
            except Exception as exc:
                results.put((iid, None, f"{type(exc).__name__}: {exc}"))

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(args.workers)]
    for t in threads:
        t.start()

    started = time.monotonic()
    n = errors = 0
    try:
        while n < len(todo):
            iid, row, err = results.get()
            with out:
                out.execute(
                    "INSERT OR REPLACE INTO checked "
                    "(inscription_id, error, checked_at) "
                    "VALUES (?,?,datetime('now'))", (iid, err))
                if row:
                    out.execute(
                        "INSERT OR REPLACE INTO inscriptions "
                        "(inscription_id, signum, extant, artefact, period_sv, "
                        " uuid, uri, text_sv, text_en, fetched_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))",
                        (row["inscription_id"], row["signum"], row["extant"],
                         row["artefact"], row["period_sv"], row["uuid"],
                         row["uri"], row["text_sv"], row["text_en"]))
            n += 1
            if err:
                errors += 1
            if n % 200 == 0 or n == len(todo):
                elapsed = time.monotonic() - started
                rate = n / elapsed if elapsed else 0
                left = (len(todo) - n) / rate if rate else 0
                print(f"  {n:,}/{len(todo):,}  {errors:,} errors  "
                      f"{rate:.1f}/s  {left/60:.0f}m left", flush=True)
    except KeyboardInterrupt:
        stop.set()
        print("stopped; rerun to resume")
        return
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2)
    if errors:
        print(f"{errors:,} failed; rerun to retry those")
    apply()


if __name__ == "__main__":
    main()
