#!/usr/bin/env python3
"""Ask JEV which family a description is actually about.

The pin already has a family, from families.py. This does not reclassify the
register. It asks one choice question -- the eleven families, plus an escape
for a text that is not about a monument at all -- and writes a row when the
answer is not the family the pin wears. A runestone described under a road
is rockart against transport, which is the mismatch worth reading by hand.

JEV is called through OpenRouter's Decisions API, model typesafe/jev-1.13.
There is no TypeSafe key. The OpenRouter key is OPEN_ROUTER_API_KEY in the
environment, or one line in ~/fl-scratch/openrouter.key. Neither is in the
repo.

Output is jsonl, one place per line, appended as each answer arrives. A
second run skips cluster ids already in the file, so a stopped run continues
rather than starting over. Places whose choice matches their family are
written too: the probabilities are what a later pass sorts by, and dropping
the agreements would make a re-run re-pay for them.

    python flag_families.py --limit 20
    python flag_families.py
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
from families import FAMILY_ORDER

KEY_FILE = os.path.expanduser("~/fl-scratch/openrouter.key")
OUT = os.path.expanduser("~/fl-scratch/family_flags.jsonl")
URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"

# What a description of that family is about, in the words the generated
# texts actually use. The id has to be the family id, because that is what
# the pin is compared against.
CRITERIA = {
    "graves": "a grave, burial mound, cairn, stone setting or grave field",
    "rockart": "a runestone, rock carving, rock painting or cup mark",
    "forts": "a hillfort, castle, fortress, rampart or battlefield",
    "religious": "a church, chapel, monastery, sacrificial site or holy well",
    "settlement": "a dwelling, house foundation, village site or farmstead",
    "farming": "a fossil field, clearance cairn, terrace or enclosure for cultivation",
    "industry": "a mill, mine, furnace, forge, quarry or ironworks",
    "transport": "an old road, hollow way, bridge, ford or milestone",
    "maritime": "a harbour, ship remains, lighthouse or seamark",
    "hunting": "a pitfall trap or other hunting trap",
    "misc": "a find spot or a remain whose type is uncertain",
    "other": "a visitor remark, a modern facility, or something that is not a monument",
}

QUESTION = {
    "family": {
        "type": "choice",
        "instructions": "What is the main thing this text describes?",
        "criteria": {fid: CRITERIA[fid] for fid in FAMILY_ORDER + ["other"]},
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
                seen.add(json.loads(line)["cluster_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return seen


def places(limit):
    conn = sqlite3.connect(paths.ro(paths.PLACES), uri=True)
    conn.row_factory = sqlite3.Row
    sql = """
        SELECT cluster_id, name, class_sv, family, content_en
        FROM features
        WHERE excluded = 0
          AND content_en IS NOT NULL AND content_en != ''
        ORDER BY score DESC
    """
    rows = conn.execute(sql).fetchall()
    conn.close()
    if limit:
        rows = rows[:limit]
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
    payload = ask(token, row["content_en"])
    answer = payload.get("answers", {}).get("family") or {}
    choice = answer.get("choice")
    return {
        "cluster_id": row["cluster_id"],
        "name": row["name"],
        "class_sv": row["class_sv"],
        "family": row["family"],
        "choice": choice,
        "flag": choice != row["family"],
        "confidence": answer.get("confidence"),
        "probabilities": answer.get("probabilities"),
        "usage": payload.get("usage"),
        "text": row["content_en"],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--limit", type=int, default=0,
                   help="only the first N places by score, for a trial")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--out", default=OUT)
    args = p.parse_args()

    token = key()
    seen = done(args.out)
    rows = [r for r in places(args.limit) if r["cluster_id"] not in seen]
    print(f"{len(rows)} to ask, {len(seen)} already in {args.out}", flush=True)
    if not rows:
        return

    lock = threading.Lock()
    flags = 0
    n = 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "a", encoding="utf-8") as out:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(one, token, r): r["cluster_id"] for r in rows}
            for fut in as_completed(futs):
                cid = futs[fut]
                try:
                    rec = fut.result()
                except Exception as e:
                    print(f"FAIL {cid}: {e}", flush=True)
                    continue
                line = json.dumps(rec, ensure_ascii=False)
                with lock:
                    out.write(line + "\n")
                    out.flush()
                    n += 1
                    if rec["flag"]:
                        flags += 1
                    if n % 50 == 0 or n == len(rows):
                        print(f"{n}/{len(rows)}  flags {flags}", flush=True)
    print(f"done. {flags} flags in this run.", flush=True)


if __name__ == "__main__":
    main()
