#!/usr/bin/env python3
"""Look around a commented place while deciding where the comment belongs.

These are for the review after flag_comments.py, one place at a time. They
read the register and the contribution mirror. They do not move or delete
anything: a comment withdrawn here would not reach the phone, and a rating
has no retraction in the log at all.

    python comment_tools.py nearby 60.62831 14.87127 800
    python comment_tools.py show 5c46ce59-9ccc-4454-9bab-cd0ded7ac205
    python comment_tools.py mismatches
"""

import argparse
import json
import math
import os
import sqlite3

import paths

FLAGS = os.path.expanduser("~/fl-scratch/comment_flags.jsonl")


def _hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def points_in_circle(lat, lng, radius_m):
    """Sites within radius_m of a point, nearest first.

    Each item is lamningsnummer, uuid, class, parish, metres, and the start
    of the surveyor's own text.
    """
    dlat = radius_m / 111_000
    dlon = radius_m / (111_000 * max(0.2, math.cos(math.radians(lat))))
    work = sqlite3.connect(paths.ro(paths.WORK), uri=True)
    rows = work.execute(
        """
        SELECT uuid, lamningsnummer, class_sv, parish, lat, lon,
               substr(coalesce(beskrivning, ''), 1, 160)
          FROM sites
         WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
           AND lat IS NOT NULL AND lon IS NOT NULL
        """,
        (lat - dlat, lat + dlat, lng - dlon, lng + dlon),
    ).fetchall()
    work.close()
    out = []
    for uuid, num, cls, parish, slat, slon, text in rows:
        metres = _hav(lat, lng, slat, slon)
        if metres > radius_m:
            continue
        out.append({
            "metres": round(metres),
            "lamningsnummer": num,
            "uuid": uuid,
            "class_sv": cls,
            "parish": parish,
            "beskrivning": text,
        })
    out.sort(key=lambda r: r["metres"])
    return out


def show(uuid):
    """The remain, and the comment and rating currently on it."""
    work = sqlite3.connect(paths.ro(paths.WORK), uri=True)
    site = work.execute(
        """
        SELECT lamningsnummer, class_sv, parish, municipality, lat, lon,
               substr(coalesce(beskrivning, ''), 1, 400)
          FROM sites WHERE uuid = ?
        """,
        (uuid,),
    ).fetchone()
    work.close()
    src = sqlite3.connect(paths.ro(paths.CONTRIBUTIONS), uri=True)
    events = []
    for kind, event_id, payload in src.execute(
        "SELECT kind, event_id, payload FROM events WHERE place_uuid = ? ORDER BY seq",
        (uuid,),
    ):
        events.append({"kind": kind, "event_id": event_id, "payload": json.loads(payload)})
    src.close()
    if not site:
        return {"uuid": uuid, "events": events}
    return {
        "uuid": uuid,
        "lamningsnummer": site[0],
        "class_sv": site[1],
        "parish": site[2],
        "municipality": site[3],
        "lat": site[4],
        "lon": site[5],
        "beskrivning": site[6],
        "events": events,
    }


def mismatches(path=FLAGS):
    """Places JEV said the comment is about something else, surest first."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("choice") == "no":
                rows.append(rec)
    rows.sort(key=lambda r: -(r.get("confidence") or 0))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("nearby")
    n.add_argument("lat", type=float)
    n.add_argument("lng", type=float)
    n.add_argument("radius", type=float, help="metres")

    s = sub.add_parser("show")
    s.add_argument("uuid")

    sub.add_parser("mismatches")
    args = p.parse_args()

    if args.cmd == "nearby":
        rows = points_in_circle(args.lat, args.lng, args.radius)
    elif args.cmd == "show":
        rows = show(args.uuid)
    else:
        rows = mismatches()
        print(f"{len(rows)} mismatches")
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
