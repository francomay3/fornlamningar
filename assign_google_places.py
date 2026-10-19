#!/usr/bin/env python3
"""Add, to the Google Places CSV, which Fornkoll place each row was given.

The CSV is the fetch. It has no site. The assignment already happened in
the app: the generated review summary was imported as a comment on a
place, and that comment is the link. This script writes the link back.
It does not decide a new one from the map.

Three ways a row is recognised, and then it stops:

    exact     The comment in the app is the CSV text, whitespace aside.
    prefix    The two texts still share a long opening (80 characters or
              more) and no other row shares as much. The summary was
              edited after import, but the beginning was kept.
    title     The comment now starts with this row's title, the title is
              not shared with another candidate, and the Google pin sits
              within a kilometre of the place the comment was put on.
              Exact matches in the data all fall inside 700 m, so a
              kilometre is the same assignment seen from the pin, not a
              search radius for a new one.

A comment that was rewritten past recognition stays unlinked, and the
row's columns are left empty. Two places given the same summary both
appear: that is what the app holds.

    python assign_google_places.py                 # counts, no write
    python assign_google_places.py --write
"""

import argparse
import csv
import json
import math
import os
import sqlite3
from collections import defaultdict

import paths

CSV_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "fornlamningar-google", "fornlamningar.csv"))

PREFIX_MIN = 80
TITLE_MIN = 8
NEAR_M = 1000


def norm(s):
    if not s:
        return ""
    s = (s.replace("\u2013", "-").replace("\u2014", "-")
         .replace("\u2212", "-").replace("\u00a0", " "))
    return " ".join(s.split())


def hav(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    x = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(min(1.0, x)))


def prefix_len(a, b, cap=500):
    n = min(len(a), len(b), cap)
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def load_comments():
    """body -> {place uuid}. Every imported summary, including ones later
    taken off the sheet: withdrawing it did not un-assign it."""
    db = sqlite3.connect(paths.ro(paths.CONTRIBUTIONS), uri=True)
    out = defaultdict(set)
    for uuid, payload in db.execute(
            "SELECT place_uuid, payload FROM events WHERE kind = 'comment'"):
        body = norm(json.loads(payload).get("body", ""))
        if body and uuid:
            out[body].add(uuid)
    db.close()
    return out


def load_labels():
    """uuid -> (name, lat, lon). The name is what the app shows."""
    labels = {}
    coords = {}
    if os.path.exists(paths.PLACES):
        db = sqlite3.connect(paths.ro(paths.PLACES), uri=True)
        for uuid, title, name, lam, lat, lon in db.execute("""
                SELECT uuid, title, name, lamningsnummer, lat, lon
                  FROM features
                 WHERE uuid IS NOT NULL AND uuid <> ''"""):
            labels[uuid] = title or name or lam or ""
            if lat is not None and lon is not None:
                coords[uuid] = (lat, lon)
        db.close()
    if os.path.exists(paths.WORK):
        db = sqlite3.connect(paths.ro(paths.WORK), uri=True)
        for uuid, name, lam, lat, lon in db.execute("""
                SELECT c.rep_uuid, c.name, s.lamningsnummer, c.lat, c.lon
                  FROM clusters c
                  LEFT JOIN sites s ON s.uuid = c.rep_uuid
                 WHERE c.rep_uuid IS NOT NULL"""):
            labels.setdefault(uuid, name or lam or "")
            if uuid not in coords and lat is not None and lon is not None:
                coords[uuid] = (lat, lon)
        db.close()
    return labels, coords


def near(row, uuids, coords):
    try:
        glat, glng = float(row["lat"]), float(row["lng"])
    except (TypeError, ValueError):
        return False
    for u in uuids:
        loc = coords.get(u)
        if loc and hav(glat, glng, loc[0], loc[1]) <= NEAR_M:
            return True
    return False


def match(rows, comments, coords):
    """placeId is not the key: two rows can share one, and a row with no
    id still needs a column. The key is the row's position."""
    assigned = {}          # row index -> (how, [uuid, ...])
    used_bodies = set()

    by_exact = comments
    for i, row in enumerate(rows):
        body = norm(row.get("comment", ""))
        if body and body in by_exact:
            assigned[i] = ("exact", sorted(by_exact[body]))
            used_bodies.add(body)

    unused = {b: u for b, u in comments.items() if b not in used_bodies}
    pending = [i for i in range(len(rows)) if i not in assigned]

    # Longest shared opening. A tie is not a match.
    taken_bodies = set()
    prefix_hits = {}
    for i in pending:
        cb = norm(rows[i].get("comment", ""))
        if len(cb) < PREFIX_MIN:
            continue
        scored = []
        for body in unused:
            n = prefix_len(cb, body)
            if n >= PREFIX_MIN:
                scored.append((n, body))
        if not scored:
            continue
        scored.sort(reverse=True)
        best_n, best_body = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0
        if best_n < second + 40:
            continue
        prefix_hits.setdefault(best_body, []).append((best_n, i))

    for body, hits in prefix_hits.items():
        hits.sort(reverse=True)
        if len(hits) > 1 and hits[0][0] < hits[1][0] + 40:
            continue
        i = hits[0][1]
        if i in assigned or body in taken_bodies:
            continue
        assigned[i] = ("prefix", sorted(unused[body]))
        taken_bodies.add(body)
        used_bodies.add(body)

    unused = {b: u for b, u in unused.items() if b not in used_bodies}
    for body, uuids in unused.items():
        cands = []
        folded = body.casefold()
        for i, row in enumerate(rows):
            if i in assigned:
                continue
            title = norm(row.get("title", "")).casefold()
            if len(title) < TITLE_MIN or not folded.startswith(title):
                continue
            if near(row, uuids, coords):
                cands.append(i)
        if len(cands) == 1:
            assigned[cands[0]] = ("title", sorted(uuids))
    return assigned


def cell(uuids, labels):
    ids = ";".join(uuids)
    names = " | ".join(labels.get(u) or u for u in uuids)
    return ids, names


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--csv", default=CSV_PATH)
    p.add_argument("--write", action="store_true",
                   help="write assigned_uuid and assigned_name back to the CSV")
    args = p.parse_args()

    with open(args.csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    comments = load_comments()
    labels, coords = load_labels()
    assigned = match(rows, comments, coords)

    how = defaultdict(int)
    places = set()
    multi = 0
    for kind, uuids in assigned.values():
        how[kind] += 1
        places.update(uuids)
        if len(uuids) > 1:
            multi += 1
    print(f"{len(rows):,} Google rows, {len(comments):,} distinct comments")
    print(f"assigned {len(assigned):,}: "
          + ", ".join(f"{k} {how[k]:,}" for k in ("exact", "prefix", "title")))
    print(f"  {len(places):,} places, {multi:,} rows point at more than one")
    print(f"  {len(rows) - len(assigned):,} rows with no assignment")
    if not args.write:
        print("\ntitle matches:")
        for i, (kind, uuids) in sorted(assigned.items()):
            if kind != "title":
                continue
            _, names = cell(uuids, labels)
            print(f"  {rows[i]['title']}  ->  {names}")
        return

    for col in ("assigned_uuid", "assigned_name"):
        if col not in fields:
            fields.append(col)
    for i, row in enumerate(rows):
        if i in assigned:
            uid, name = cell(assigned[i][1], labels)
        else:
            uid, name = "", ""
        row["assigned_uuid"] = uid
        row["assigned_name"] = name
    tmp = args.csv + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, args.csv)
    print(f"wrote {args.csv}")


if __name__ == "__main__":
    main()
