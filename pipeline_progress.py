#!/usr/bin/env python3
"""
Where the pipeline is right now, and when it will finish.

Two modes. `--sample` takes one measurement and appends it; `run_pipeline.sh`
runs it in a loop in the background for the whole run. With no arguments it
prints a report, which is the thing you actually type.

EVERY NUMBER HERE IS MEASURED, NONE IS ESTIMATED IN ADVANCE.
------------------------------------------------------------
The rate comes from comparing samples taken during THIS run, so the ETA
reflects the machine as it is behaving now -- thermal throttling, a model
that got slower on long sources, another process competing for the GPU. A
figure worked out before the run from an average seconds-per-place would be
wrong in the one way that matters: it would be confident.

Two consequences, both deliberate:

  - the first minute has no ETA. Two samples are needed for a rate, and
    saying "calculating" is more useful than extrapolating from one point
  - a stage that has NOT STARTED gets no estimate at all. Translation could
    be guessed at from the generation rate, and it would be a guess across
    two different jobs -- generating from scratch and rewriting in English
    are not the same work. So it is reported as unknown until it begins and
    the total says so

PROGRESS IS COUNTED FROM THE OUTPUT DATABASE, NOT FROM A LOG
------------------------------------------------------------
`done` is a COUNT over generated.sqlite, not a tally the runner keeps. If a
worker dies, a row is rolled back or the run is restarted with --from, the
count still says what actually exists, because it is the same question the
next run will ask. A counter in a log file would drift and, worse, would
drift in the optimistic direction.

Usage:
    python3 pipeline_progress.py            # the report
    python3 pipeline_progress.py --watch    # the report, refreshed
    python3 pipeline_progress.py --sample   # one measurement (the runner)
"""

import argparse
import json
import os
import sqlite3
import sys
import time

import paths

STATE = os.path.join(paths.DATA, "pipeline_state.json")
SAMPLES = os.path.join(paths.DATA, "pipeline_samples.jsonl")

# Stages whose progress can be counted. Everything else is a few minutes and
# reported as elapsed only -- a progress bar on a 40-second stage is noise.
COUNTED = ("descriptions", "translate")

# Rate is taken over a trailing window rather than over the whole stage, so a
# slow first hour stops dragging the estimate around once the machine settles.
# 45 minutes is long enough to smooth out one stuck place taking three minutes
# and short enough to notice a real slowdown.
WINDOW_S = 45 * 60


# --- state, written by run_pipeline.sh -------------------------------------


def read_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(state: dict) -> None:
    # Written via a temp file and renamed: the monitor may read this at any
    # moment, and a half-written JSON file reads as a crashed run.
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE)


# --- measurement -----------------------------------------------------------


def target_ids(top: int) -> list[str]:
    """The clusters this run is meant to describe.

    Imported from build_descriptions rather than reimplemented: if the two
    disagreed about what is eligible, the progress bar would fill to 94% and
    stop, which is the most annoying possible bug in a tool whose only job is
    to tell you when something finishes.
    """
    import build_descriptions as bd

    sites = sqlite3.connect(paths.ro(paths.WORK), uri=True)
    sites.row_factory = sqlite3.Row
    try:
        return bd.eligible(sites, None, False, None, top or None)
    finally:
        sites.close()


def measure(stage: str, top: int) -> tuple[int, int] | None:
    """(done, total) for a counted stage, or None if it cannot be counted."""
    if stage not in COUNTED or not os.path.exists(paths.GENERATED):
        return None
    import describe_place as dp

    ids = target_ids(top)
    if not ids:
        return None
    out = sqlite3.connect(paths.ro(paths.GENERATED), uri=True)
    try:
        # A temp table rather than a 10,000-term IN clause, which SQLite
        # accepts and then plans badly.
        out.execute("CREATE TEMP TABLE want(cluster_id TEXT PRIMARY KEY)")
        out.executemany("INSERT OR IGNORE INTO want VALUES (?)", ((i,) for i in ids))
        if stage == "descriptions":
            done, = out.execute(
                "SELECT count(*) FROM ai_descriptions a JOIN want w USING (cluster_id) "
                "WHERE a.content <> '' AND a.prompt_version = ?",
                (dp.PROMPT_VERSION,)).fetchone()
            total = len(ids)
        else:
            # Translation's denominator is what Swedish text EXISTS, not the
            # target: it cannot translate a description that was never
            # written, and counting those as pending would leave the bar
            # permanently short of the end.
            done, = out.execute(
                "SELECT count(*) FROM ai_descriptions a JOIN want w USING (cluster_id) "
                "WHERE a.content_en IS NOT NULL AND a.content_en <> ''").fetchone()
            total, = out.execute(
                "SELECT count(*) FROM ai_descriptions a JOIN want w USING (cluster_id) "
                "WHERE a.content <> ''").fetchone()
        return done, total
    finally:
        out.close()


def sample() -> None:
    state = read_state()
    cur = state.get("current") or {}
    stage = cur.get("name")
    if not stage:
        return
    got = measure(stage, int(state.get("top") or 0))
    row = {"ts": time.time(), "stage": stage}
    if got:
        row["done"], row["total"] = got
    with open(SAMPLES, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def read_samples(stage: str) -> list[dict]:
    if not os.path.exists(SAMPLES):
        return []
    out = []
    with open(SAMPLES, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn last line while the sampler is writing
            if row.get("stage") == stage and "done" in row:
                out.append(row)
    return out


# --- formatting ------------------------------------------------------------


def dur(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, m = divmod(seconds // 60, 60)
    if h >= 24:
        return f"{h // 24}d {h % 24}h"
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {seconds % 60:02d}s"
    return f"{seconds}s"


def bar(frac: float, width: int = 28) -> str:
    filled = int(round(frac * width))
    return "█" * filled + "·" * (width - filled)


def rate_per_s(samples: list[dict]) -> float | None:
    """Items per second over the trailing window, by first-to-last difference.

    Not a least-squares fit: the series is a monotonic counter, so the only
    thing a fit would add is sensitivity to the sampler's own jitter.
    """
    if len(samples) < 2:
        return None
    cutoff = samples[-1]["ts"] - WINDOW_S
    window = [s for s in samples if s["ts"] >= cutoff] or samples[-2:]
    if len(window) < 2:
        return None
    span = window[-1]["ts"] - window[0]["ts"]
    grew = window[-1]["done"] - window[0]["done"]
    if span <= 0 or grew <= 0:
        return None
    return grew / span


# How long without a sample before a run is presumed dead. The sampler writes
# every 60s for as long as run_pipeline.sh lives, whatever stage it is in, so
# silence means the run is gone -- not that it is busy.
STALE_S = 5 * 60


def last_activity() -> float | None:
    """When this run last proved it was alive."""
    try:
        return os.path.getmtime(SAMPLES)
    except OSError:
        return None


def report() -> int:
    state = read_state()
    if not state:
        print("no run recorded. start one with ./run_pipeline.sh")
        return 1

    # THE RUN IS CHECKED FOR A PULSE BEFORE ANYTHING IS REPORTED ABOUT IT.
    #
    # Without this the tool reads a dead run's last state and presents it as
    # live, rate and ETA and all. That is not a cosmetic failure: on
    # 2026-09-18 the pipeline died at 21:23 on an unhandled HTTP 500, and this
    # command went on reporting "5.3/min, finishes around 18:39" from samples
    # that had stopped eleven hours earlier. Franco read that and reasonably
    # concluded the stage was slow. A monitor that cannot say "this is dead"
    # is worse than no monitor, because it manufactures confidence.
    seen = last_activity()
    if seen is not None and not state.get("finished_at"):
        silent = time.time() - seen
        if silent > STALE_S:
            cur = (state.get("current") or {}).get("name", "?")
            print("!! THE RUN IS NOT ALIVE")
            print(f"   no sign of life for {dur(silent)}, stage '{cur}'")
            print(f"   last error, if any: tail {os.path.join(paths.DATA, 'pipeline_run.log')}")
            print(f"   resume with: ./run_pipeline.sh --from {cur}")
            print()

    now = time.time()
    started = state.get("started_at", now)
    stages = state.get("stages", [])
    done_stages = {d["name"]: d for d in state.get("done", [])}
    cur = state.get("current") or {}
    finished = state.get("finished_at")

    print(f"pipeline  run {state.get('run_id','?')}   "
          f"elapsed {dur(now - started)}")
    if finished:
        print(f"FINISHED after {dur(finished - started)}")
    print()

    for name in stages:
        if name in done_stages:
            print(f"  [x] {name:14} {dur(done_stages[name]['seconds'])}")
        elif name == cur.get("name"):
            print(f"  [>] {name:14} running for "
                  f"{dur(now - cur.get('started_at', now))}")
        else:
            print(f"  [ ] {name:14} -")
    print()

    if finished or not cur.get("name"):
        return 0

    stage = cur["name"]
    samples = read_samples(stage)
    if not samples:
        if stage in COUNTED:
            print(f"{stage}: starting, no measurement yet")
        else:
            print(f"{stage}: short stage, no progress to count")
        return 0

    last = samples[-1]
    done, total = last["done"], last["total"]
    frac = done / total if total else 0.0
    print(f"{stage}")
    print(f"  {bar(frac)}  {frac*100:5.1f}%   {done:,} / {total:,}")

    per_s = rate_per_s(samples)
    if per_s is None:
        print("  rate: measuring (needs a second sample; the sampler runs "
              "every 60s)")
        return 0

    left = max(0, total - done)
    eta = left / per_s
    print(f"  rate: {per_s * 60:.1f}/min   (measured over the last "
          f"{dur(min(WINDOW_S, last['ts'] - samples[0]['ts']))})")
    print(f"  {left:,} left -> {dur(eta)}   finishes around "
          f"{time.strftime('%a %H:%M', time.localtime(now + eta))}")

    # Only what has been observed. A stage that has not begun is named, not
    # estimated -- see the module docstring.
    rest = [n for n in stages
            if n not in done_stages and n != stage]
    if rest:
        unknown = [n for n in rest if n in COUNTED]
        print(f"  then: {', '.join(rest)}")
        if unknown:
            print(f"  ({', '.join(unknown)} is long and has not started, so "
                  "it is not in the estimate above)")
    return 0


def begin_run(stages: list[str], top: int) -> None:
    # A fresh samples file per run. Rates are computed from it, and samples
    # from last week's run would be indistinguishable from this one's.
    if os.path.exists(SAMPLES):
        os.remove(SAMPLES)
    write_state({
        "run_id": time.strftime("%Y%m%d-%H%M%S"),
        "started_at": time.time(),
        "stages": stages,
        "top": top,
        "done": [],
        "current": None,
    })


def begin_stage(name: str) -> None:
    state = read_state()
    state["current"] = {"name": name, "started_at": time.time()}
    write_state(state)


def end_stage(name: str, seconds: float) -> None:
    state = read_state()
    state.setdefault("done", []).append({"name": name, "seconds": seconds})
    state["current"] = None
    write_state(state)


def end_run() -> None:
    state = read_state()
    state["current"] = None
    state["finished_at"] = time.time()
    write_state(state)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--begin-run", metavar="S1,S2,...")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--begin-stage", metavar="NAME")
    ap.add_argument("--end-stage", nargs=2, metavar=("NAME", "SECONDS"))
    ap.add_argument("--end-run", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--every", type=int, default=30)
    a = ap.parse_args()

    # State transitions, called by run_pipeline.sh. Each one is a whole
    # process, which is wasteful and correct: the runner is bash, and the
    # alternative is bash writing JSON.
    if a.begin_run:
        begin_run([s for s in a.begin_run.split(",") if s], a.top)
        return 0
    if a.begin_stage:
        begin_stage(a.begin_stage)
        return 0
    if a.end_stage:
        end_stage(a.end_stage[0], float(a.end_stage[1]))
        return 0
    if a.end_run:
        end_run()
        return 0
    if a.sample:
        sample()
        return 0
    if a.watch:
        try:
            while True:
                # \033[H\033[J rather than clear(1): keeps working over ssh
                # into a terminal that has no terminfo entry.
                sys.stdout.write("\033[H\033[J")
                report()
                sys.stdout.flush()
                time.sleep(a.every)
        except KeyboardInterrupt:
            return 0
    return report()


if __name__ == "__main__":
    sys.exit(main())
