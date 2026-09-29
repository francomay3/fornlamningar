#!/usr/bin/env python3
"""Ask JEV whether a visitor comment is about this remain's type.

The only two things it sees are the lämningstyp and the comment. A mill
comment on a dam wall is a mismatch; a comment that never names a kind of
place is not, because there is nothing to contradict the type.

Same call as flag_families.py: OpenRouter's Decisions API, model
typesafe/jev-1.13. The key is OPEN_ROUTER_API_KEY, or one line in
~/fl-scratch/openrouter.key.

One row per place, appended as each answer arrives. A second run skips
place uuids already in the file.

    python flag_comments.py --uuid 5c46ce59-9ccc-4454-9bab-cd0ded7ac205
    python flag_comments.py
"""

import argparse
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import paths

KEY_FILE = os.path.expanduser("~/fl-scratch/openrouter.key")
OUT = os.path.expanduser("~/fl-scratch/comment_flags.jsonl")
URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"

QUESTION = {
    "match": {
        "type": "choice",
        "instructions": (
            "The line starting Lämningstyp is the Swedish name of the kind "
            "of remain this record is. The rest is a visitor comment. Does "
            "the comment describe that kind of place?"
        ),
        "criteria": {
            "yes": (
                "The comment is about this kind of remain. Praise, practical "
                "advice, or a mood, with no other kind of place named, also "
                "counts."
            ),
            "no": (
                "The comment is about a different kind of place than this "
                "type. A mill comment on a dam, a church comment on a grave, "
                "a restaurant comment on a runestone."
            ),
            "unclear": "The comment never says what the place is.",
        },
    }
}


def key():
    for name in ("OPEN_ROUTER_API_KEY", "OPENROUTER_API_KEY"):
        env = os.environ.get(name, "").strip()
        if env:
            return env
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            line = f.read().strip()
    except FileNotFoundError:
        sys.exit(f"no OpenRouter key. Put one line in {KEY_FILE}")
    if not line or line.startswith("#"):
        sys.exit(f"{KEY_FILE} is empty")
    return line.splitlines()[0].strip()


def done(path):
    seen = set()
    if not os.path.exists(path):
        return seen
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                seen.add(json.loads(line)["uuid"])
            except (json.JSONDecodeError, KeyError):
                continue
    return seen


def places(only):
    src = sqlite3.connect(paths.ro(paths.CONTRIBUTIONS), uri=True)
    work = sqlite3.connect(paths.ro(paths.WORK), uri=True)
    rows = []
    q = "SELECT place_uuid, payload FROM events WHERE kind = 'comment'"
    args = []
    if only:
        q += " AND place_uuid = ?"
        args.append(only)
    for uuid, payload in src.execute(q, args):
        body = json.loads(payload).get("body") or ""
        site = work.execute(
            "SELECT class_sv, lamningsnummer, lat, lon, parish FROM sites WHERE uuid = ?",
            (uuid,),
        ).fetchone()
        if not site or not site[0] or not body.strip():
            continue
        rows.append({
            "uuid": uuid,
            "class_sv": site[0],
            "lamningsnummer": site[1],
            "lat": site[2],
            "lon": site[3],
            "parish": site[4],
            "comment": body,
        })
    src.close()
    work.close()
    return rows


def ask(token, text):
    body = json.dumps({
        "model": MODEL,
        "state": text,
        "questions": QUESTION,
    }).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    delay = 1.0
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code not in (408, 409, 429, 500, 502, 503, 529) or attempt == 5:
                raise RuntimeError(f"HTTP {e.code}: {detail}") from e
            time.sleep(delay)
            delay = min(delay * 2, 30)
        except (urllib.error.URLError, TimeoutError):
            if attempt == 5:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30)


def one(token, row):
    state = f"Lämningstyp: {row['class_sv']}\n\n{row['comment']}"
    payload = ask(token, state)
    answer = payload.get("answers", {}).get("match") or {}
    choice = answer.get("choice")
    return {
        "uuid": row["uuid"],
        "lamningsnummer": row["lamningsnummer"],
        "class_sv": row["class_sv"],
        "parish": row["parish"],
        "lat": row["lat"],
        "lon": row["lon"],
        "choice": choice,
        "flag": choice == "no",
        "confidence": answer.get("confidence"),
        "probabilities": answer.get("probabilities"),
        "comment": row["comment"],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--uuid", help="ask about one place and print the answer")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out", default=OUT)
    args = p.parse_args()

    token = key()
    seen = set() if args.uuid else done(args.out)
    rows = [r for r in places(args.uuid) if r["uuid"] not in seen]
    print(f"{len(rows)} to ask, {len(seen)} already in {args.out}", flush=True)
    if not rows:
        return

    if args.uuid:
        rec = one(token, rows[0])
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        return

    lock = threading.Lock()
    flags = 0
    n = 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as out:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(one, token, r): r["uuid"] for r in rows}
            for fut in as_completed(futs):
                uuid = futs[fut]
                try:
                    rec = fut.result()
                except Exception as e:
                    print(f"FAIL {uuid}: {e}", flush=True)
                    continue
                with lock:
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
                    n += 1
                    if rec["flag"]:
                        flags += 1
                    if n % 50 == 0 or n == len(rows):
                        print(f"{n}/{len(rows)}  flags {flags}", flush=True)
    print(f"done. {flags} flags in this run.", flush=True)


if __name__ == "__main__":
    main()
