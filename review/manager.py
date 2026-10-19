#!/usr/bin/env python3
"""Hand places to review agents, one each, without two of them sharing one.

    review/.venv/bin/python review/manager.py                  # who would be handed, no agents
    review/.venv/bin/python review/manager.py --run 1          # one site, so the result can be read
    review/.venv/bin/python review/manager.py --run 200        # a night: one after another
    review/.venv/bin/python review/manager.py --run 80 --parallel 4
    review/.venv/bin/python review/manager.py --site <uuid>    # this one, even if already reviewed

For each place: dossier.py fetches everything into a workspace, the agent
reads it and writes decision.json, apply.py writes that to the admin API
and signs the place off. results.jsonl keeps one line per place: how long,
how many tool calls, what was decided, what failed.

The list comes from the admin API. A place already verified, marked not
interesting, or set aside is not handed out. Places this process has handed
out and not yet heard back from are remembered in inflight.json, so a second
run does not take them. A row older than the lease is taken again: the agent
is gone and the place was not closed. A place whose writes failed is in
failed.json and is not handed out again until that file is cleared.
"""

import argparse
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

API = os.environ.get("FL_API", "https://franco-may.com/api/fornlamningar")
INFLIGHT = os.path.join(HERE, "inflight.json")
RUNLOCK = os.path.join(HERE, "run.lock")
FAILED = os.path.join(HERE, "failed.json")
RESULTS = os.path.join(HERE, "results.jsonl")
LOGS = os.path.join(HERE, "logs")
PROMPT = os.path.join(HERE, "prompt.md")
# Outside the repo. A workspace inside it would hand the agent the pipeline
# notes in the root AGENTS.md, which are not this job. One folder per slot,
# not per place, so Cursor does not keep a project for every place.
WORK = os.path.join(tempfile.gettempdir(), "fl-review")

# Kinds that are usually a point in a field. The empty lane is this list.
# A high score with no photographs is the bare lane instead, even for one
# of these kinds: that place is on the map and has nothing to show.
EMPTY_KINDS = {
    "Fyndplats",
    "Fornlämningsliknande lämning",
    "Fornlämningsliknande bildning",
    "Övrigt",
}

# Round-robin order. bare and drawer are the high-score work; empty is the
# likely-nothing work; rest is everything still open, so it is not stranded.
LANE_ORDER = ("bare", "drawer", "empty", "rest")
LEASE_S = 2 * 60 * 60
LOCK = threading.Lock()
# Set on SIGINT or SIGTERM. The site already open is finished; no new one starts.
STOP = threading.Event()
_LOCK_FD = None


def acquire_run_lock():
    """One review process. A second one exits before it takes any place."""
    global _LOCK_FD
    fd = os.open(RUNLOCK, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        sys.exit("a review is already running")
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode())
    _LOCK_FD = fd


def _ask_stop(signum, _frame):
    if STOP.is_set():
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
        return
    STOP.set()
    print("stopping after the site that is open", flush=True)


def ensure_token():
    """FL_AGENT_TOKEN, the same secret the server reads. Never printed.

    The process environment wins. Otherwise the value is taken from
    franco-may/.env.local, which is the copy that is not committed.
    """
    value = os.environ.get("FL_AGENT_TOKEN", "").strip()
    if not value:
        path = os.path.normpath(
            os.path.join(HERE, "..", "..", "franco-may", ".env.local")
        )
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("FL_AGENT_TOKEN="):
                        value = line.split("=", 1)[1].strip().strip('"')
                        break
        if value:
            os.environ["FL_AGENT_TOKEN"] = value
    if not value:
        sys.exit("FL_AGENT_TOKEN is not set")
    return value


def fetch_places():
    req = urllib.request.Request(
        f"{API}/places",
        headers={"Authorization": f"Bearer {ensure_token()}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            body = json.load(res)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:300]
        sys.exit(f"places: {err.code} {detail}")
    rows = body.get("places")
    if not isinstance(rows, list):
        sys.exit("places: response has no list")
    return rows


def _load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def load_inflight():
    now = time.time()
    return {
        uid: stamp
        for uid, stamp in _load(INFLIGHT).items()
        if isinstance(stamp, (int, float)) and now - stamp < LEASE_S
    }


def open_rows(rows, held):
    failed = _load(FAILED)
    out = []
    for row in rows:
        if row.get("verified_at") or row.get("uninteresting") or row.get("aside"):
            continue
        if row.get("id") in held or row.get("id") in failed:
            continue
        out.append(row)
    return out


def lane_of(row):
    kind = row.get("kind") or ""
    photos = row.get("photos") or 0
    score = row.get("score")
    if photos == 0 and score is not None and kind not in EMPTY_KINDS:
        return "bare"
    if photos > 0 and not row.get("prioritized") and score is not None:
        return "drawer"
    if kind in EMPTY_KINDS:
        return "empty"
    return "rest"


def score_key(row, empty):
    score = row.get("score")
    if score is None:
        return (1, 0)
    # Empty places: low score first. The others: high score first.
    return (0, score if empty else -score)


def backend_of(row):
    """Local only chooses photos. A place with nothing to choose needs the agent."""
    return "local" if (row.get("photos") or 0) > 0 and (row.get("sources") or 0) > 1 else "agent"


def _buckets():
    return {name: [] for name in LANE_ORDER}


def _take(buckets, n):
    chosen = []
    while len(chosen) < n and any(buckets.values()):
        for name in LANE_ORDER:
            if len(chosen) >= n:
                break
            if buckets[name]:
                chosen.append((name, buckets[name].pop(0)))
    return chosen


def pick_for(rows, n, held, backend="auto"):
    """(local, agent, left).

    In auto, Cursor gets at most half of the run and never more places than
    the local model, so the two queues stay one to one when both have work.
    One local worker then outlasts the agents. If one side has nothing left,
    the run is the other side: those places would not be reached otherwise.
    """
    pools = {"local": _buckets(), "agent": _buckets()}
    for row in open_rows(rows, held):
        pools[backend_of(row)][lane_of(row)].append(row)
    for pool in pools.values():
        for name, bucket in pool.items():
            bucket.sort(key=lambda row: score_key(row, name == "empty"))
    n_local = sum(len(b) for b in pools["local"].values())
    n_agent = sum(len(b) for b in pools["agent"].values())
    half = n // 2
    if backend == "local" or n_agent == 0:
        local, agent = _take(pools["local"], n), []
    elif backend == "agent" or n_local == 0:
        local, agent = [], _take(pools["agent"], n)
    else:
        cursor_n = min(n_agent, n_local, half)
        local_n = min(n_local, n - cursor_n)
        local = _take(pools["local"], local_n)
        agent = _take(pools["agent"], cursor_n)
    left = {name: len(pools["local"][name]) + len(pools["agent"][name]) for name in LANE_ORDER}
    return local, agent, left


def fill_prompt(row):
    with open(PROMPT, encoding="utf-8") as f:
        text = f.read()
    fields = {
        "uuid": row.get("id") or "",
        "name": row.get("name") or "",
        "kind": row.get("kind") or "",
        "api": API,
    }
    for key, value in fields.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def show(chosen):
    if not chosen:
        print("nothing to hand out")
        return
    for lane, row in chosen:
        score = row.get("score")
        score_s = "  —" if score is None else f"{score:5.1f}"
        name = (row.get("name") or "").replace("\n", " ")
        print(
            f"{lane:<6} {score_s}  "
            f"photos {row.get('photos') or 0:<3} "
            f"sources {row.get('sources') or 0:<3} "
            f"{row.get('kind') or '—':<32} "
            f"{name[:40]:<40} {row.get('id')}"
        )


def _count_tools(log_path):
    """Tool calls in a stream-json log, by name."""
    counts = {}
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "tool_call" and ev.get("subtype") == "started":
                    call = ev.get("tool_call") or {}
                    name = next(iter(call), "?")
                    counts[name] = counts.get(name, 0) + 1
    except OSError:
        pass
    return counts


def review_one(lane, row, slot, model, timeout, dry, backend="agent"):
    from dossier import build

    uid = row["id"]
    work = os.path.join(WORK, f"slot-{slot}")
    t0 = time.time()
    result = {"uuid": uid, "name": row.get("name"), "kind": row.get("kind"),
              "lane": lane, "backend": backend, "model": model, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        build(uid, work, row.get("kind") or "")
    except Exception as err:
        result.update(ok=False, error=f"dossier: {err}")
        return result
    result["dossier_s"] = round(time.time() - t0, 1)

    if backend == "auto":
        # Photos and a source besides the register: choosing photos, local.
        # The rest needs research, the agent.
        has = (row.get("photos") or 0) > 0 and (row.get("sources") or 0) > 1
        backend = "local" if has else "agent"
        result["backend"] = backend
    if backend == "local":
        from local import decide
        t1 = time.time()
        result["model"] = model or os.environ.get("FL_LOCAL_MODEL", "qwen3.6:35b-a3b")
        try:
            got = decide(work, result["model"], timeout=timeout)
            result["local"] = {k: v for k, v in got.items() if k != "decision"}
        except Exception as err:
            result.update(ok=False, error=f"local: {err}",
                          agent_s=round(time.time() - t1, 1))
            return result
        result["agent_s"] = round(time.time() - t1, 1)
        return _finish(result, work, uid, dry, t0)

    log_path = os.path.join(LOGS, f"{uid}.log")
    cmd = ["agent", "-p", "--trust", "--force", "--sandbox", "disabled",
           "--workspace", work, "--output-format", "stream-json"]
    if model:
        cmd += ["--model", model]
    cmd.append(fill_prompt(row))
    t1 = time.time()
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, cwd=work, env=os.environ.copy(),
                                stdout=log, stderr=subprocess.STDOUT)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = "timeout"
    result["agent_s"] = round(time.time() - t1, 1)
    result["exit"] = code
    result["tools"] = _count_tools(log_path)
    result["model"] = model or _cursor_model(log_path)
    return _finish(result, work, uid, dry, t0)


def _cursor_model(log_path):
    """The model the Cursor CLI actually started, from its first log line."""
    try:
        with open(log_path, encoding="utf-8") as fh:
            row = json.loads(fh.readline())
    except (OSError, json.JSONDecodeError):
        return ""
    return row.get("model") or ""


def _finish(result, work, uid, dry, t0):
    from apply import apply

    applied = apply(work, uid, dry=dry, backend=result.get("backend"),
                    model=result.get("model") or None)
    result.update(
        ok=applied.get("ok"),
        error=applied.get("error"),
        decision=applied.get("decision"),
        writes=[w for w in applied.get("writes") or [] if not w["ok"]],
    )
    if dry:
        result["plan"] = applied.get("plan")
    keep = os.path.join(LOGS, uid)
    os.makedirs(keep, exist_ok=True)
    for name in ("sheet.jpg", "official.jpg", "dossier.md", "decision.json"):
        if os.path.exists(os.path.join(work, name)):
            shutil.copy2(os.path.join(work, name), keep)
    result["total_s"] = round(time.time() - t0, 1)
    return result


def record(result):
    with LOCK:
        with open(RESULTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        held = load_inflight()
        held.pop(result["uuid"], None)
        _save(INFLIGHT, held)
        if not result.get("ok") and not result.get("dry"):
            failed = _load(FAILED)
            failed[result["uuid"]] = result.get("error") or "failed"
            _save(FAILED, failed)
    d = result.get("decision") or {}
    tools = sum((result.get("tools") or {}).values())
    print(
        f"{'ok ' if result.get('ok') else 'ERR'} {result.get('total_s', 0):6.0f}s "
        f"{(result.get('backend') or ''):<5} tools {tools:<3} {result.get('lane') or '':<6} "
        f"{(result.get('name') or '')[:34]:<34} "
        f"{'aside ' if d.get('aside') else ''}{'unint ' if d.get('uninteresting') else ''}"
        f"{'flag ' if d.get('flag') else ''}{result.get('error') or ''}",
        flush=True,
    )


def run(groups, model, timeout, dry):
    """groups: [(backend, [(lane, row), ...], workers)]. One local worker, several agents."""
    os.makedirs(LOGS, exist_ok=True)
    signal.signal(signal.SIGINT, _ask_stop)
    signal.signal(signal.SIGTERM, _ask_stop)
    queues = []
    for backend, chosen, workers in groups:
        if chosen and workers > 0:
            queues.append((backend, list(chosen), workers))
    with LOCK:
        held = load_inflight()
        now = time.time()
        for _, queue, _ in queues:
            for _, row in queue:
                held[row["id"]] = now
        _save(INFLIGHT, held)

    def worker(slot, backend, queue):
        while True:
            with LOCK:
                if STOP.is_set() or not queue:
                    return
                lane, row = queue.pop(0)
            record(review_one(lane, row, slot, model, timeout, dry, backend)
                   | ({"dry": True} if dry else {}))

    threads = []
    slot = 0
    for backend, queue, workers in queues:
        for _ in range(workers):
            threads.append(threading.Thread(target=worker, args=(slot, backend, queue)))
            slot += 1
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Places never started are free again. The one that was open was recorded.
    with LOCK:
        held = load_inflight()
        left = 0
        for _, queue, _ in queues:
            for _, row in queue:
                held.pop(row["id"], None)
                left += 1
        _save(INFLIGHT, held)
    if left:
        print(f"stopped, {left} not started", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=int, metavar="N",
                        help="review N places. without this, only the list is printed")
    parser.add_argument("--site", action="append", metavar="UUID",
                        help="review this place, even if it is already closed")
    parser.add_argument("--parallel", type=int, default=4,
                        help="Cursor agents at once. The local model is always one (default 4)")
    parser.add_argument("--backend", choices=("auto", "agent", "local"), default="auto",
                        help="auto: half the run at most is Cursor, one local at a time. "
                             "agent: Cursor only. local: Ollama only")
    parser.add_argument("--model", default=os.environ.get("FL_REVIEW_MODEL", ""),
                        help="model. empty is the CLI default, or qwen3.6:35b-a3b for local")
    parser.add_argument("--timeout", type=int, default=900,
                        help="seconds one agent may take (default 900)")
    parser.add_argument("--dry", action="store_true",
                        help="build and decide, write nothing to the API")
    parser.add_argument("--limit", type=int, default=12,
                        help="how many rows to print when not running (default 12)")
    args = parser.parse_args()
    if args.run is not None or args.site:
        acquire_run_lock()
    ensure_token()
    rows = fetch_places()
    if args.site:
        by_id = {r.get("id"): r for r in rows}
        local, agent = [], []
        for u in args.site:
            row = by_id.get(u) or {"id": u, "name": u}
            kind = args.backend if args.backend != "auto" else backend_of(row)
            (local if kind == "local" else agent).append(("site", row))
        held, left = load_inflight(), None
    else:
        n = args.run if args.run is not None else args.limit
        if n < 1:
            sys.exit("the count has to be at least 1")
        held = load_inflight()
        local, agent, left = pick_for(rows, n, held, args.backend)
        print("open after this pick: " + ", ".join(f"{k} {left[k]}" for k in LANE_ORDER))
    cursor_n = max(1, args.parallel)
    print(f"in flight: {len(held)}")
    print(f"local {len(local)} (1 at a time), cursor {len(agent)} ({cursor_n if agent else 0} at a time)")
    show(local)
    show(agent)
    if args.run is None and not args.site:
        print("dry list. pass --run N to review.")
        return
    run([("local", local, 1), ("agent", agent, cursor_n)],
        args.model, args.timeout, args.dry)


if __name__ == "__main__":
    main()
