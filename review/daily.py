#!/usr/bin/env python3
"""Review 80 places, at most once a day, when this machine is logged in or wakes.

launchd runs this at login. sleepwatcher runs it on wake. A day starts at
07:00 local time and runs until 06:59 the next morning. If a review is
already going, or one already started in this day, this exits without
starting another.
"""

import datetime
import fcntl
import os
import sys
import time
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STAMP = os.path.join(HERE, "daily_stamp")
LOCK = os.path.join(HERE, "daily.lock")
RUNLOCK = os.path.join(HERE, "run.lock")
N = 80
DAY_START_HOUR = 7
PY = os.path.join(HERE, ".venv", "bin", "python")


def day_of(ts):
    """The calendar day, with the boundary at 07:00."""
    dt = datetime.datetime.fromtimestamp(ts)
    if dt.hour < DAY_START_HOUR:
        dt -= datetime.timedelta(days=1)
    return dt.date()


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def _locked(path):
    """True when another process holds the lock file."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return True
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    return False


def ollama_up():
    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=2)
            return True
        except Exception:
            time.sleep(2)
    return False


def main():
    os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("already running")
        return 0
    try:
        started = 0.0
        if os.path.exists(STAMP):
            try:
                started = float(open(STAMP, encoding="utf-8").read().strip() or 0)
            except ValueError:
                started = 0.0
        if started and day_of(started) == day_of(time.time()):
            log("already ran today (the day starts at 07:00), skipping")
            return 0
        if _locked(RUNLOCK):
            log("a review is already running")
            return 0
        if not ollama_up():
            log("ollama is not up, not starting")
            return 0
        with open(STAMP, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PATH"] = ":".join([
            os.path.expanduser("~/.local/bin"),
            "/usr/local/bin",
            "/opt/homebrew/bin",
            env.get("PATH", "/usr/bin:/bin"),
        ])
        log(f"starting {N}")
        proc = subprocess.run(
            [PY, os.path.join(HERE, "manager.py"), "--run", str(N)],
            cwd=HERE, env=env,
        )
        log(f"finished {proc.returncode}")
        return proc.returncode
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main() or 0)
