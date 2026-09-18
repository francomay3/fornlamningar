#!/usr/bin/env python3
"""
Stage 13: freeze this run's payload as a numbered, verifiable release.

WHAT A RELEASE IS
-----------------
A directory named after a generation number, holding a copy of every file a
phone consumes, plus a manifest listing each one with its size and SHA-256.
Nothing in a release is ever modified after it is written.

WHY IMMUTABLE FILES AND A MUTABLE MANIFEST, AND NOT THE OBVIOUS THING
---------------------------------------------------------------------
The obvious thing is one well-known URL per file, overwritten on each run. It
breaks in a way that is almost impossible to debug: a phone part-way through
downloading descriptions.sv.db when the file is replaced gets the first half
of one database and the second half of another. SQLite opens it happily -- the
header is valid -- and fails later, on one row, on a phone in a field, days
after the deploy that caused it.

With the bytes at a name that includes the generation, that cannot happen: a
download either completes or is retried against the same immutable bytes. The
only mutable object is `manifest.json`, which is small enough to be written
atomically and cheap enough to fetch on every launch.

It also means going back is editing one line, and that the app can be told to
pin a generation while a bad one is investigated.

WHY THE EVENTS CURSOR IS IN THE MANIFEST
----------------------------------------
Since the pipeline pulls the contribution log before scoring, a place's rank
depends on user data, so the same commit run twice gives different output and
"why did this site drop?" has no answer. `events_seq` is the highest event the
scoring saw, which is what makes a release reproducible: that commit, plus the
log up to that number, produces these files. Without it the export is a fact
with no provenance.

WHAT THIS DOES NOT DO: UPLOAD
-----------------------------
Deliberately. Where these are hosted costs money and the choice is Franco's --
R2 against Vercel Blob is decided on egress, not on storage, because each
install pulls tens of megabytes. So this writes a release that is ready to
upload and prints the command; nothing here touches a network or needs a
credential.

Usage:
    python3 make_release.py
    python3 make_release.py --dry-run
    python3 make_release.py --releases-dir /Volumes/big/releases
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time

import paths

# The files a phone consumes. Every one is a pure function of this run, and
# together they are the whole payload: the markers, the text in both
# languages, the offline ground, and the two map styles.
#
# The styles are in here even though they are tiny and change rarely. Not for
# the bytes -- for the coupling: `filterFamilies.ts` and the glyph names are
# generated from the same export, so a style from one generation and markers
# from another can disagree about which icons exist. Versioning them together
# is what makes that impossible rather than unlikely.
PAYLOAD = (
    "points.geojson",
    "descriptions.sv.db",
    "descriptions.en.db",
    "offline-basemap.geojson",
    "basemap-style.json",
    "basemap-style-dark.json",
)

APP = os.environ.get("APP", "../fornlamningar-app")
ASSETS = "assets/data"
RELEASES = os.path.join(paths.DATA, "releases")
GEN_FILE = os.path.join(paths.DATA, "generation")


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def next_generation() -> int:
    """A monotonic integer, and it has to be an integer.

    `ASSET_VERSION` in the app is a content hash, which answers "is this the
    same data?" and cannot answer "is this NEWER data?" -- so a phone holding
    generation 12 cannot tell whether the manifest's hash is an upgrade or the
    rollback it already refused. A counter can. Kept in its own file rather
    than derived from the directory listing, so pruning old releases to save
    disk cannot reissue a number that has already shipped.
    """
    try:
        with open(GEN_FILE, encoding="utf-8") as f:
            current = int(f.read().strip() or 0)
    except (OSError, ValueError):
        current = 0
    return current + 1


def events_seq() -> int | None:
    """The highest contribution the scoring for this release could have seen."""
    if not os.path.exists(paths.CONTRIBUTIONS):
        return None
    conn = sqlite3.connect(paths.ro(paths.CONTRIBUTIONS), uri=True)
    try:
        row = conn.execute("SELECT max(seq) FROM events").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def describe_counts() -> dict:
    """Coverage, recorded because a release that is WORSE should be visible.

    A generation with fewer descriptions than the last one is not necessarily
    wrong -- the top ten thousand moves -- but it is always worth knowing
    before it ships, and afterwards it is the first thing you want when
    something looks thin.
    """
    if not os.path.exists(paths.GENERATED):
        return {}
    conn = sqlite3.connect(paths.ro(paths.GENERATED), uri=True)
    try:
        sv, = conn.execute(
            "SELECT count(*) FROM ai_descriptions WHERE content <> ''").fetchone()
        en, = conn.execute(
            "SELECT count(*) FROM ai_descriptions "
            "WHERE content_en IS NOT NULL AND content_en <> ''").fetchone()
        return {"descriptions_sv": sv, "descriptions_en": en}
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default=APP)
    ap.add_argument("--releases-dir", default=RELEASES)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src_dir = os.path.join(a.app, ASSETS)
    missing = [n for n in PAYLOAD if not os.path.exists(os.path.join(src_dir, n))]
    if missing:
        print(f"missing from {src_dir}: {', '.join(missing)}", file=sys.stderr)
        print("  run scripts/sync-assets.sh in the app repo first", file=sys.stderr)
        return 1

    gen = next_generation()
    files = []
    for name in PAYLOAD:
        path = os.path.join(src_dir, name)
        files.append({
            "name": name,
            "bytes": os.path.getsize(path),
            "sha256": sha256(path),
        })

    manifest = {
        "generation": gen,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "events_seq": events_seq(),
        "coverage": describe_counts(),
        "files": files,
    }

    total = sum(f["bytes"] for f in files)
    print(f"  generation {gen}   {len(files)} files   {total/1e6:.1f} MB")
    for f in files:
        print(f"    {f['name']:26} {f['bytes']/1e6:7.2f} MB  {f['sha256'][:12]}")
    if manifest["events_seq"] is not None:
        print(f"  events_seq {manifest['events_seq']}")

    if a.dry_run:
        print("  --dry-run: nothing written")
        return 0

    dest = os.path.join(a.releases_dir, str(gen))
    if os.path.exists(dest):
        # A release directory is immutable, so this is never an overwrite: it
        # means the counter and the directory disagree, which is a bug worth
        # stopping for rather than resolving by clobbering shipped bytes.
        print(f"{dest} already exists -- refusing to overwrite a release",
              file=sys.stderr)
        return 1
    os.makedirs(dest)
    for name in PAYLOAD:
        shutil.copy2(os.path.join(src_dir, name), os.path.join(dest, name))
    with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # The counter is bumped LAST, after the bytes are on disk. The other order
    # would burn a generation number on a run that died half-copied, and the
    # next release would then claim to be two generations newer than it is.
    with open(GEN_FILE, "w", encoding="utf-8") as f:
        f.write(str(gen) + "\n")

    # `latest` is the only mutable thing here, and it is a convenience for
    # scripts on this machine -- NOT the thing a phone reads. What a phone
    # reads is manifest.json at a fixed URL, written by whatever uploads this.
    link = os.path.join(a.releases_dir, "latest")
    tmp = link + ".tmp"
    if os.path.islink(tmp) or os.path.exists(tmp):
        os.remove(tmp)
    os.symlink(str(gen), tmp)
    os.replace(tmp, link)

    print(f"  written to {dest}")
    print()
    print("  NOT uploaded: where these are hosted is still undecided (R2 vs")
    print("  Vercel Blob, and the deciding number is egress). When it is:")
    print(f"    <upload> {dest}/* -> datasets/{gen}/")
    print(f"    <upload> {dest}/manifest.json -> manifest.json   (last, atomically)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
