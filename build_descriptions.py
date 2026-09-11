#!/usr/bin/env python3
"""
Generate visitor descriptions for every place, best-scoring first, resumably.

Stop it whenever you like. Each finished description is committed on its own
before the next one starts, so Ctrl-C costs you at most the place currently in
flight, and starting again picks up exactly where it stopped. Nothing is
checkpointed: the pending set is derived by asking which eligible clusters have
no current row yet, the same approach that made the K-samsok crawl restartable.

Deliberately a SEPARATE database from sites.sqlite.
`build_sites.py` drops and recreates that file from the raw crawl on every
`run_pipeline.sh --from 1`. Hours of local generation stored there would
evaporate the first time you rebuilt the pipeline. This file is never touched
by any other stage.

Reads:  src/data/sites.sqlite       (read-only)
Writes: src/data/descriptions.sqlite

Usage:
    python3 build_descriptions.py --limit 200          # try it on the best 200
    python3 build_descriptions.py                      # everything, resumable
    python3 build_descriptions.py --only-flagged        # redo the suspect ones
    python3 build_descriptions.py --status
"""

import argparse
import hashlib
import json
import math
import os
import queue
import signal
import sqlite3
import sys
import threading
import time

import describe_place as dp

import paths

OUT_DB = paths.GENERATED

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_descriptions (
    cluster_id     TEXT PRIMARY KEY,
    uuid           TEXT,
    lamning        TEXT,
    -- Swedish is canonical: it is what the model actually produced from the
    -- Swedish source, with no translation step to go wrong. English is a
    -- second pass over this text and can be redone independently.
    title          TEXT,
    content        TEXT,
    title_en       TEXT,
    content_en     TEXT,
    translated_by  TEXT,
    translated_at  TEXT,
    model          TEXT,
    prompt_version INTEGER,
    -- Hash of exactly what the model was shown. A re-crawl that rewrites a
    -- RAA description changes this, which marks the row stale without having
    -- to diff the text.
    source_hash    TEXT,
    flags          TEXT,
    elapsed_ms     INTEGER,
    created_at     TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ai_flags ON ai_descriptions(flags);
CREATE INDEX IF NOT EXISTS idx_ai_uuid  ON ai_descriptions(uuid);

CREATE TABLE IF NOT EXISTS failures (
    cluster_id   TEXT PRIMARY KEY,
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    last_attempt TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

stop = threading.Event()


def source_hash(model_input):
    blob = json.dumps(model_input, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def open_out(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def eligible(sites, limit, include_empty, near=None, top=None):
    """Every place worth describing, in the order we want them generated.

    Score order is what makes stopping early sensible rather than arbitrary:
    whenever you interrupt it, what got written is the part of the map people
    are most likely to look at.

    `near` swaps that for distance from a point, which is the order you want
    while reviewing: a hundred places you can actually go and check beat a
    hundred scattered over a country. Distance is computed in Python rather
    than SQL because sqlite3 ships without trigonometric functions on some
    builds, and 100k rows sort instantly anyway.

    `top` restricts the pool to the N best-scoring places -- pass the same N
    the tile export uses. Without it the pool is every eligible place in the
    country, 104k of them, and only a tenth of those ever reach a tile. That
    matters most in combination with `near`: of the 150 places nearest one
    house, only 28 were in the exported 10,000, so 122 descriptions would have
    been generated for pins nobody can click.
    """
    where = ["c.lon IS NOT NULL", "sc.excluded_hard = 0", "sc.excluded_soft = 0"]
    if not include_empty:
        # A place whose only text is the register's generic disclaimer has
        # nothing to rewrite. Asking anyway wastes seconds per place and
        # invites the model to fill the silence.
        where += ["c.best_description IS NOT NULL",
                  "length(c.best_description) > 40",
                  "COALESCE(c.all_boilerplate, 0) = 0"]
    # Applied as a subquery so `near` sorts within the exported set rather
    # than the whole country.
    pool = ""
    if top:
        pool = f"""AND c.cluster_id IN (
            SELECT c2.cluster_id FROM clusters c2
              JOIN scores s2 ON s2.cluster_id = c2.cluster_id
             WHERE c2.lon IS NOT NULL AND s2.excluded_hard = 0
               AND s2.excluded_soft = 0
             ORDER BY s2.score_intrinsic DESC LIMIT {int(top)})"""

    if near is None:
        rows = sites.execute(f"""
            SELECT c.cluster_id FROM clusters c
              JOIN scores sc ON sc.cluster_id = c.cluster_id
             WHERE {' AND '.join(where)} {pool}
             ORDER BY sc.score_intrinsic DESC
             {f'LIMIT {int(limit)}' if limit else ''}""").fetchall()
        return [r["cluster_id"] for r in rows]

    lat0, lon0 = near
    kx = 111.320 * math.cos(math.radians(lat0))     # km per degree of longitude
    rows = sites.execute(f"""
        SELECT c.cluster_id, c.lon, c.lat FROM clusters c
          JOIN scores sc ON sc.cluster_id = c.cluster_id
         WHERE {' AND '.join(where)} {pool}""").fetchall()
    ranked = sorted(
        rows, key=lambda r: ((r["lat"] - lat0) * 110.574) ** 2
                            + ((r["lon"] - lon0) * kx) ** 2)
    if limit:
        ranked = ranked[:int(limit)]
    return [r["cluster_id"] for r in ranked]


def done_map(out, prompt_version):
    return {r[0]: r[1] for r in out.execute(
        "SELECT cluster_id, source_hash FROM ai_descriptions WHERE prompt_version = ?",
        (prompt_version,))}


def run_translate(out, a):
    """Fill the English columns. Independent of generation, and restartable."""
    rows = out.execute(
        "SELECT cluster_id, title, content FROM ai_descriptions "
        "WHERE content <> '' AND (content_en IS NULL OR content_en = '') "
        "ORDER BY rowid" + (f" LIMIT {int(a.limit)}" if a.limit else "")
    ).fetchall()
    if not rows:
        print("nothing to translate")
        return
    model = a.translate_model or dp.TRANSLATE_MODEL
    print(f"{len(rows):,} to translate with {model}")
    signal.signal(signal.SIGINT, lambda *_: (stop.set(), print("\n  stopping...")))
    n, t0 = 0, time.time()
    for cid, title, content in rows:
        if stop.is_set():
            break
        en, elapsed, err = dp.translate({"title": title, "content": content},
                                        model=model, host=a.host)
        if err:
            continue
        out.execute("""UPDATE ai_descriptions SET title_en=?, content_en=?,
                       translated_by=?, translated_at=CURRENT_TIMESTAMP
                       WHERE cluster_id=?""",
                    (en["title"], en["content"], model, cid))
        out.commit()
        n += 1
        if n % 10 == 0:
            rate = n / max(time.time() - t0, 1e-9)
            print(f"  {n:,}/{len(rows):,}  {rate*60:.0f}/min  "
                  f"eta {(len(rows)-n)/rate/3600:.1f} h", flush=True)
    print(f"\n{n:,} translated in {(time.time()-t0)/60:.1f} min")


def run_retitle(sites, out, a):
    """Rewrite the titles of rows that already have approved body text.

    A prompt change that only affects the title should not cost a full rerun:
    the body text of these rows was read and approved, and regenerating it
    would risk changing text nobody asked to change. Titles are rewritten from
    the same source plus the finished Swedish body, then translated on their
    own.
    """
    rows = out.execute(
        "SELECT cluster_id, title, content FROM ai_descriptions "
        "WHERE content <> '' ORDER BY rowid"
        + (f" LIMIT {int(a.limit)}" if a.limit else "")).fetchall()
    if not rows:
        print("nothing to retitle")
        return
    print(f"{len(rows):,} titles to rewrite at prompt v{dp.PROMPT_VERSION} "
          f"with {a.model}")
    signal.signal(signal.SIGINT,
                  lambda *_: (stop.set(), print("\n  stopping...")))
    tmodel = a.translate_model or dp.TRANSLATE_MODEL
    n, changed, t0 = 0, 0, time.time()
    for cid, old_title, content in rows:
        if stop.is_set():
            break
        pl = dp.payload(sites, cid)
        if pl is None:
            continue
        title, _, err = dp.retitle(pl["model_input"], content,
                                   model=a.model, host=a.host)
        if err or not title:
            continue
        en, _, terr = dp.translate_title(title, model=tmodel, host=a.host)
        out.execute("""UPDATE ai_descriptions
                       SET title = ?, title_en = ?, prompt_version = ?
                       WHERE cluster_id = ?""",
                    (title, None if terr else en, dp.PROMPT_VERSION, cid))
        out.commit()
        n += 1
        changed += title != old_title
        if n % 10 == 0:
            rate = n / max(time.time() - t0, 1e-9)
            print(f"  {n:,}/{len(rows):,}  {rate*60:.0f}/min", flush=True)
    print(f"\n{n:,} retitled in {(time.time()-t0)/60:.1f} min "
          f"({changed:,} actually changed)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=dp.DB)
    p.add_argument("--out", default=OUT_DB)
    p.add_argument("--host", default=dp.HOST)
    p.add_argument("--model", default=dp.DEFAULT_MODEL)
    p.add_argument("--limit", type=int, help="only the first N in the order")
    p.add_argument("--top", type=int, default=10000,
                   help="restrict to the N best-scoring places, i.e. the ones "
                        "build_tiles.py actually exports. 0 for every "
                        "eligible place in the country")
    p.add_argument("--near", metavar="LAT,LON",
                   help="order by distance from this point instead of by "
                        "score, for reviewing one area you know well")
    p.add_argument("--concurrency", type=int, default=1,
                   help="parallel requests to Ollama. Raising this only helps "
                        "if OLLAMA_NUM_PARALLEL allows it server-side")
    p.add_argument("--include-empty", action="store_true",
                   help="also send places whose only text is the disclaimer")
    p.add_argument("--force", action="store_true", help="regenerate everything")
    p.add_argument("--only-flagged", action="store_true",
                   help="regenerate just the rows a check flagged")
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--translate", action="store_true",
                   help="second pass: fill the English columns for rows that "
                        "already have Swedish")
    p.add_argument("--translate-model", default=None)
    p.add_argument("--retitle", action="store_true",
                   help="rewrite only the titles of rows that already have "
                        "body text, and retranslate those titles. For a "
                        "prompt change that does not touch the body")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()

    if not os.path.exists(a.db):
        sys.exit(f"missing {a.db} - run ./run_pipeline.sh first")

    near = None
    if a.near:
        lat, lon = (float(x) for x in a.near.split(","))
        near = (lat, lon)

    sites = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    sites.row_factory = sqlite3.Row
    out = open_out(a.out)

    if a.status:
        n, = out.execute("SELECT count(*) FROM ai_descriptions").fetchone()
        flagged, = out.execute(
            "SELECT count(*) FROM ai_descriptions WHERE flags <> ''").fetchone()
        fails, = out.execute("SELECT count(*) FROM failures").fetchone()
        total = len(eligible(sites, None, a.include_empty, top=a.top or None))
        print(f"{n:,} of {total:,} eligible places described "
              f"({100.0*n/max(total,1):.1f}%)")
        print(f"{flagged:,} flagged, {fails:,} with failures")
        for m, c in out.execute("SELECT model, count(*) FROM ai_descriptions "
                                "GROUP BY 1 ORDER BY 2 DESC"):
            print(f"  {m}: {c:,}")
        for f, c in out.execute(
                "SELECT flags, count(*) FROM ai_descriptions WHERE flags <> '' "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT 10"):
            print(f"  flag {f}: {c:,}")
        return

    if a.retitle:
        return run_retitle(sites, out, a)

    if a.translate:
        return run_translate(out, a)

    ids = eligible(sites, a.limit, a.include_empty, near, a.top or None)
    if a.only_flagged:
        flagged = {r[0] for r in out.execute(
            "SELECT cluster_id FROM ai_descriptions WHERE flags <> ''")}
        ids = [c for c in ids if c in flagged]
    elif not a.force:
        # Done means: a row exists at the current prompt version. Staleness
        # from a re-crawl is NOT detected here on purpose -- checking it would
        # mean building every payload just to hash it, which is most of the
        # cost of the run. `source_hash` is stored so a stale row can be found
        # later; use --force to redo everything.
        done = set(done_map(out, dp.PROMPT_VERSION))
        blocked = {r[0] for r in out.execute(
            "SELECT cluster_id FROM failures WHERE attempts >= ?",
            (a.max_attempts,))}
        ids = [c for c in ids if c not in done and c not in blocked]

    if not ids:
        print("nothing to do - everything eligible is already described")
        return

    print(f"{len(ids):,} places to describe with {a.model} "
          f"(prompt v{dp.PROMPT_VERSION}"
          + (f", nearest first around {near[0]:.4f},{near[1]:.4f}" if near
             else ", best score first")
          + (f", within the exported top {a.top:,}" if a.top else "") + ")")

    signal.signal(signal.SIGINT, lambda *_: (
        stop.set(), print("\n  stopping after the places in flight...")))

    work = queue.Queue()
    results = queue.Queue()
    for cid in ids:
        work.put(cid)

    # One connection per reader thread: sqlite objects are not shareable, and
    # the source database is read-only so there is nothing to coordinate.
    def worker():
        conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        while not stop.is_set():
            try:
                cid = work.get_nowait()
            except queue.Empty:
                return
            try:
                pl = dp.payload(conn, cid)
                if pl is None:
                    results.put(("fail", cid, "no such cluster", None))
                    continue
                res, elapsed, err = dp.generate(pl["model_input"], a.model, a.host)
                if err:
                    results.put(("fail", cid, err, None))
                    continue
                flags = dp.check(res, pl["model_input"])
                results.put(("ok", cid, pl, (res, flags, elapsed)))
            except Exception as exc:                      # noqa: BLE001
                results.put(("fail", cid, f"{type(exc).__name__}: {exc}", None))

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(max(1, a.concurrency))]
    for t in threads:
        t.start()

    n = flagged = failed = 0
    t0 = time.time()
    pending = len(ids)
    while pending > 0:
        try:
            kind, cid, info, extra = results.get(timeout=0.5)
        except queue.Empty:
            # Nothing in flight and nobody left to produce anything: either
            # the queue drained or Ctrl-C stopped the workers.
            if not any(t.is_alive() for t in threads):
                break
            continue
        pending -= 1
        if kind == "fail":
            failed += 1
            out.execute("""
                INSERT INTO failures(cluster_id, attempts, last_error)
                VALUES (?, 1, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                    attempts = attempts + 1, last_error = excluded.last_error,
                    last_attempt = CURRENT_TIMESTAMP""", (cid, str(info)[:400]))
            out.commit()
            continue

        pl = info
        res, flags, elapsed = extra
        # Committed one row at a time. Generation costs seconds, so batching
        # would buy nothing measurable and would turn Ctrl-C into lost work.
        out.execute("""
            INSERT INTO ai_descriptions(cluster_id, uuid, lamning, title,
                content, model, prompt_version, source_hash, flags, elapsed_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(cluster_id) DO UPDATE SET
                uuid=excluded.uuid, lamning=excluded.lamning,
                title=excluded.title, content=excluded.content,
                model=excluded.model, prompt_version=excluded.prompt_version,
                source_hash=excluded.source_hash, flags=excluded.flags,
                elapsed_ms=excluded.elapsed_ms,
                created_at=CURRENT_TIMESTAMP""",
            (pl["cluster_id"], pl["uuid"], pl["lamning"], res["title"],
             res["content"], a.model, dp.PROMPT_VERSION,
             source_hash(pl["model_input"]), ",".join(flags),
             int(elapsed * 1000)))
        out.commit()
        out.execute("DELETE FROM failures WHERE cluster_id = ?", (cid,))
        out.commit()
        n += 1
        if flags:
            flagged += 1
        if n % 10 == 0 or pending == 0:
            rate = n / max(time.time() - t0, 1e-9)
            eta = pending / rate if rate else 0
            print(f"  {n:,}/{len(ids):,}  {rate*60:.0f}/min  "
                  f"flagged {flagged}  failed {failed}  "
                  f"eta {eta/3600:.1f} h", flush=True)

    print(f"\n{n:,} written, {flagged:,} flagged, {failed:,} failed "
          f"in {(time.time()-t0)/60:.1f} min")
    if stop.is_set():
        print("stopped early - rerun to continue from here")
    out.close()


if __name__ == "__main__":
    main()
