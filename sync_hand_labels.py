#!/usr/bin/env python3
"""Refresh the admin rows of hand_labels.csv.

The file stays the ground truth build_labels.py reads. The rows a person
typed (Street View, the labyrint pass) are left as they are. Two lists from
the admin are rewritten every time this runs, and so is the Google set:

  verified by a person, and not marked uninteresting   label 1
  verified by an agent                                 not a label
  uninteresting, verified or not                       label 0
  a Google place with no assignment, at
  least 3 stars and more than 4 reviews,
  that names a register record             label 0.85

Uninteresting wins over verified. A Google row does not overwrite a row
already in the file, neither a hand-typed one nor an admin one. A place
with no lamningsnummer cannot go in this file; those are counted and left
out.

fl_uninteresting stays a table of its own. A 0 in this file teaches the
fit. It does not take the place off the map: that is the admin label
build_labels loads from uninteresting.jsonl, and the reason is Veinge 197,
which sat at rank 4,549 after it had been flagged until the export started
reading the flag.

    python3 sync_hand_labels.py
"""

import csv
import json
import math
import os
import re
import sqlite3
import unicodedata
from collections import defaultdict

import paths

HAND = "hand_labels.csv"
VERIFIED = os.path.join(paths.DATA, "verified.jsonl")
UNINTERESTING = os.path.join(paths.DATA, "uninteresting.jsonl")
GOOGLE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "fornlamningar-google", "fornlamningar.csv"))

POINT_M = 25.0
POLY_EXTRA_M = 40.0
POLY_CAP_M = 400.0
STOP = {
    "ancient", "burial", "castle", "church", "field", "fornborg", "gamla",
    "grave", "graves", "gravfalt", "kyrka", "kyrkoruin", "monument", "mound",
    "norra", "old", "ostra", "place", "plats", "ruin", "ruiner", "ruins",
    "runestone", "runsten", "runstenar", "slott", "sodra", "stone", "stones",
    "sweden", "sverige", "vastra",
}
LNUM = re.compile(r"L\d+:\d+")
SIG = re.compile(
    r"\b(u|so|og|vs|vg|na|dr|hs|gs|vr|sm)\s*#?\s*(\d{1,4})\b", re.I)


def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.casefold()).strip()


def tokens(s):
    return [t for t in fold(s).split() if len(t) >= 4 and t not in STOP]


def hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    x = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(min(1.0, x)))


def jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def note_of(row):
    if len(row) >= 4:
        return row[3]
    if len(row) == 3:
        return row[2]
    return ""


def generated(note):
    note = note or ""
    return note.startswith("admin:") or note.startswith("google:")


def read_hand(path):
    """Lines typed by hand, in order. Rows this script wrote are dropped."""
    kept_lines = []
    seen = set()
    if not os.path.exists(path):
        return kept_lines, seen
    with open(path, newline="", encoding="utf-8") as f:
        raw = f.read().splitlines()
    skip_comment = False
    for line in raw:
        if line.startswith("# --- admin") or line.startswith("# --- google"):
            skip_comment = True
            continue
        if skip_comment and (not line.strip() or line.startswith("#")):
            continue
        skip_comment = False
        if not line.strip() or line.startswith("#"):
            kept_lines.append(line)
            continue
        row = next(csv.reader([line]))
        if len(row) < 2 or generated(note_of(row)):
            continue
        kept_lines.append(line)
        seen.add(row[0].strip())
    while kept_lines and kept_lines[-1] == "":
        kept_lines.pop()
    return kept_lines, seen


def lamn_of(conn, uuids):
    """place uuid -> lamningsnummer. The hand file is keyed on that."""
    out = {}
    ids = [u for u in uuids if u]
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for uid, lamn in conn.execute(
                f"SELECT uuid, lamningsnummer FROM sites "
                f"WHERE uuid IN ({marks}) AND lamningsnummer IS NOT NULL",
                chunk):
            out[uid] = lamn
    return out


def reach(poly, w, h):
    if poly and w and h:
        return min(POLY_CAP_M, 0.5 * max(w, h) + POLY_EXTRA_M)
    return POINT_M


def google_lamns(conn):
    """Unassigned Google rows that name a register record.

    The pin of a long polygon sits hundreds of metres from the stored
    middle. Björn Järnsidas hög is the case: the sign is 271 m from the
    centroid of a 540 m field, and the name is what makes it that field
    rather than the rune fragment 22 m away.
    """
    sites = []
    for uid, lon, lat, lamn, title, poly, w, h, cid in conn.execute("""
            SELECT s.uuid, s.lon, s.lat, s.lamningsnummer, coalesce(s.title,''),
                   s.has_polygon, s.env_width_m, s.env_height_m, sc.cluster_id
              FROM sites s
              JOIN site_clusters sc ON sc.uuid = s.uuid
             WHERE s.lon IS NOT NULL AND s.lamningsnummer IS NOT NULL"""):
        sites.append((uid, lon, lat, lamn, title or "", poly, w, h, cid))
    names = dict(conn.execute("SELECT cluster_id, coalesce(name,'') FROM clusters"))
    grid = defaultdict(list)
    for i, s in enumerate(sites):
        grid[(int(s[2] * 50), int(s[1] * 50))].append(i)

    found = {}
    unmatched = 0
    with open(GOOGLE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if (r.get("assigned_uuid") or "").strip():
            continue
        try:
            rating = float(r["rating"]) if (r.get("rating") or "").strip() else None
            reviews = float(r["reviews"]) if (r.get("reviews") or "").strip() else None
            lat, lon = float(r["lat"]), float(r["lng"])
        except (TypeError, ValueError):
            continue
        if rating is None or reviews is None or rating < 3 or reviews <= 4:
            continue
        title = r.get("title") or ""
        wanted = set(LNUM.findall(title))
        sigs = {(m.group(1).casefold(), m.group(2)) for m in SIG.finditer(title)}
        gt = set(tokens(title))
        best = None
        cy, cx = int(lat * 50), int(lon * 50)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for i in grid.get((cy + dy, cx + dx), ()):
                    s = sites[i]
                    d = hav(lat, lon, s[2], s[1])
                    if d > reach(s[5], s[6], s[7]):
                        continue
                    cname = names.get(s[8], "")
                    why = False
                    if s[3] in wanted:
                        why = True
                    else:
                        blob = f"{fold(s[4])} {fold(cname)} {fold(s[3])}"
                        if gt and any(t in blob for t in gt):
                            why = True
                        elif any(num in fold(cname) or num in fold(s[4])
                                 for _, num in sigs):
                            why = True
                    if why and (best is None or d < best[0]):
                        best = (d, s[3], title)
        if best:
            found.setdefault(best[1], best[2])
        else:
            unmatched += 1
    return found, unmatched


def main():
    conn = sqlite3.connect(f"file:{paths.WORK}?mode=ro", uri=True)
    # An agent sign-off takes the place out of the queue. It does not
    # teach the fit. A person's later click clears by_agent and then it does.
    verified = {
        r["place_uuid"]
        for r in jsonl(VERIFIED)
        if not r.get("by_agent")
    }
    dull = {r["place_uuid"] for r in jsonl(UNINTERESTING)}
    lamn = lamn_of(conn, verified | dull)
    missing = (verified | dull) - set(lamn)
    google, google_left = google_lamns(conn)
    conn.close()

    kept_lines, seen = read_hand(HAND)
    # An admin mark replaces a hand-typed row for the same record. The
    # button is the later judgement.
    fresh_lines = []
    replaced = []
    for line in kept_lines:
        if not line.strip() or line.startswith("#"):
            fresh_lines.append(line)
            continue
        row = next(csv.reader([line]))
        lam = row[0].strip()
        uuids = [u for u, n in lamn.items() if n == lam]
        if any(u in dull or u in verified for u in uuids):
            replaced.append(lam)
            continue
        fresh_lines.append(line)
    while fresh_lines and fresh_lines[-1] == "":
        fresh_lines.pop()
    seen = set()
    for line in fresh_lines:
        if line.strip() and not line.startswith("#"):
            seen.add(next(csv.reader([line]))[0].strip())

    by_lamn = defaultdict(set)
    for uid, n in lamn.items():
        by_lamn[n].add(uid)
    admin_rows = []
    n_zero = n_one = 0
    for n, uids in sorted(by_lamn.items()):
        if uids & dull:
            admin_rows.append([n, "0", "3", "admin:uninteresting"])
            n_zero += 1
        elif uids & verified:
            admin_rows.append([n, "1", "3", "admin:verified"])
            n_one += 1
    used = {row[0] for row in admin_rows}
    google_rows = []
    for n, title in sorted(google.items()):
        if n in seen or n in used:
            continue
        google_rows.append([n, "0.85", "2", f"google:{title}"])

    import io
    if admin_rows:
        admin_buf = io.StringIO()
        csv.writer(admin_buf).writerows(admin_rows)
    if google_rows:
        gbuf = io.StringIO()
        csv.writer(gbuf).writerows(google_rows)
    parts = ["\n".join(fresh_lines)]
    if admin_rows:
        parts += ["", "# --- admin. Replaced every pipeline run.",
                  admin_buf.getvalue().rstrip("\n")]
    if google_rows:
        parts += ["", "# --- google, no assignment, at least 3 stars and "
                  "more than 4 reviews, matched to a register record.",
                  gbuf.getvalue().rstrip("\n")]
    with open(HAND, "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    print(f"hand labels: {n_one} verified, {n_zero} not interesting, "
          f"{len(google_rows)} google at 0.85")
    print(f"  kept {len(seen)} hand-typed rows, replaced {len(replaced)} "
          f"that the admin now marks")
    print(f"  {len(missing)} admin uuids are not in sites")
    print(f"  {google_left} google rows matched no register record")


if __name__ == "__main__":
    main()
