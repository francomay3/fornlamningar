#!/usr/bin/env python3
"""
Draw a stratified sample of clusters for hand labelling.

Why stratified and not random: a random sample of 245,860 clusters is 99%
forgettable, so it produces almost no information. Sampling across score bands
instead gives three things at once —

  * verified NEGATIVES, which the label set currently has none of (all 5,192
    automatic labels are positives, so the only "negative" today is the base
    rate);
  * CALIBRATION: is the top of the ranking actually better than the middle, or
    is the ordering noise?
  * a check on the FILTERS: one band is drawn from the clusters the blacklist
    excludes, so a wrong exclusion becomes visible.

Output is a CSV keyed on `lamningsnummer`, which is what `hand_labels.csv`
already uses, so filled rows merge straight back in.

Usage:
    python sample_for_review.py --n 20
    python sample_for_review.py --n 20 --seed 7 --out review_2.csv
    python sample_for_review.py --merge review_20260908.csv
"""

import argparse
import csv
import os
import random
import sqlite3
import sys
import time

import numpy as np

import paths
from build_signals import (PointGrid, densify, gpkg_wkb,
                           wkb_linestring_points)

DB = paths.WORK
WAYS = "src/data/osm/sweden_ways.gpkg"
HAND = "hand_labels.csv"

# Highway classes a car can drive and that Google tends to have Street View for.
# Deliberately excludes `service` (driveways and parking aisles), `track`
# (forest and field roads, usually unsurfaced) and every foot/cycle class:
# `dist_to_way_m` in the signals table is the union of ALL ways, so a site can
# sit 5 m from a footpath and have no Street View at all -- which is exactly
# what made the first review sample hard to check from a desk.
DRIVABLE = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential",
    "living_street",
}

# Numbered public roads, where Google's Street View coverage in Sweden is close
# to complete. Rural `unclassified` and `residential` are drivable but often
# uncovered, which is why 8 of the first 20 samples could not be checked at all.
MAJOR = {
    "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link",
}
ROAD_SETS = {"drivable": DRIVABLE, "major": MAJOR}

# (name, description, predicate over percentile 0-100 where 100 = best)
# The last band is drawn from EXCLUDED clusters instead of by percentile.
BANDS = [
    ("top1",     "top 1% — should be obviously good"),
    ("p60_70",   "middle of the ranking"),
    ("p30_40",   "lower third"),
    ("bottom5",  "bottom 5% of what the app would still show"),
    ("excluded", "excluded by the class blacklist — is the exclusion right?"),
]

FIELDS = [
    "lamningsnummer", "label", "certainty", "note",   # <- you fill these three
    "band", "score", "percentile",
    "name", "class", "n_sites", "municipality", "parish",
    "road_m", "way_m", "board_m", "lat", "lon",
    "description", "fornsok", "maps",
]


def drivable_road_grid(path=WAYS, classes=None):
    """Nearest-point index over the selected road classes."""
    classes = classes or DRIVABLE
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    chunks = []
    for highway, blob in conn.execute(
            "SELECT highway, geom FROM ways WHERE geom IS NOT NULL"):
        if highway not in classes:
            continue
        for pts in wkb_linestring_points(gpkg_wkb(blob)):
            chunks.append(densify(pts))
    conn.close()
    allp = np.concatenate(chunks)
    print(f"  drivable-road index: {len(allp):,} points")
    return PointGrid(allp[:, 0], allp[:, 1])


def already_labelled(path):
    seen = set()
    if not os.path.exists(path):
        return seen
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(l for l in f if l.strip() and not l.startswith("#")):
            if row:
                seen.add(row[0].strip())
    return seen


def fetch(conn, n_per_band, seen, rng, road_grid=None, max_road=None):
    """Pick n_per_band clusters from each band, skipping ones already labelled."""
    base = """
        SELECT c.cluster_id, c.name, c.dominant_class, c.n_sites,
               c.municipality, c.parish, c.lat, c.lon, c.best_description,
               sc.score_intrinsic AS score,
               sc.excluded_hard, sc.excluded_soft,
               g.dist_to_way_m, g.dist_to_board_m,
               (SELECT s.lamningsnummer FROM site_clusters x
                  JOIN sites s ON s.uuid = x.uuid
                 WHERE x.cluster_id = c.cluster_id
                 ORDER BY s.description_len DESC, s.uuid LIMIT 1) AS lamn,
               (SELECT s.uuid FROM site_clusters x
                  JOIN sites s ON s.uuid = x.uuid
                 WHERE x.cluster_id = c.cluster_id
                 ORDER BY s.description_len DESC, s.uuid LIMIT 1) AS uuid,
               c.centroid_e, c.centroid_n
        FROM clusters c
        JOIN scores sc  ON sc.cluster_id = c.cluster_id
        JOIN signals g  ON g.cluster_id  = c.cluster_id
        WHERE c.lat IS NOT NULL
    """
    # The visible pool, ranked. Percentile is computed over this pool only,
    # because that is what the app would actually show.
    pool = conn.execute(
        base + " AND sc.excluded_hard=0 AND sc.excluded_soft=0"
             + " ORDER BY sc.score_intrinsic DESC").fetchall()
    excluded = conn.execute(
        base + " AND (sc.excluded_hard=1 OR sc.excluded_soft=1)").fetchall()
    total = len(pool)
    print(f"pool: {total:,} visible clusters, {len(excluded):,} excluded")

    def slice_pct(lo, hi):
        """lo/hi are percentiles where 100 = best."""
        a = int(total * (1 - hi / 100.0))
        b = int(total * (1 - lo / 100.0))
        return pool[a:b]

    candidates = {
        "top1":     slice_pct(99, 100),
        "p60_70":   slice_pct(60, 70),
        "p30_40":   slice_pct(30, 40),
        "bottom5":  slice_pct(0, 5),
        "excluded": excluded,
    }

    out = []
    road_cache = {}

    def road_dist(r):
        """Distance to the nearest drivable road, or None."""
        if road_grid is None or r["centroid_e"] is None:
            return None
        key = r["cluster_id"]
        if key not in road_cache:
            road_cache[key] = road_grid.nearest(r["centroid_e"], r["centroid_n"],
                                                max_search=3000.0)
        return road_cache[key]

    for band, _desc in BANDS:
        rows = [r for r in candidates[band] if r["lamn"] and r["lamn"] not in seen]
        if max_road is not None:
            rng.shuffle(rows)
            keep, checked = [], 0
            # Test candidates one at a time and stop as soon as the band is
            # full, so we never compute distances for the whole pool.
            for r in rows:
                checked += 1
                d = road_dist(r)
                if d is not None and d <= max_road:
                    keep.append(r)
                if len(keep) >= n_per_band:
                    break
            print(f"  {band:<10} {len(keep)} within {max_road:.0f} m of a road "
                  f"(checked {checked})")
            rows = keep
        if not rows:
            print(f"  ! band {band}: no candidates left")
            continue
        picked = rows[:n_per_band] if max_road is not None else \
            rng.sample(rows, min(n_per_band, len(rows)))
        for r in picked:
            # percentile within the visible pool; excluded rows have none
            pct = ""
            if not (r["excluded_hard"] or r["excluded_soft"]):
                try:
                    pct = round(100.0 * (total - pool.index(r)) / total, 1)
                except ValueError:
                    pct = ""
            desc = " ".join((r["best_description"] or "").split())[:300]
            out.append({
                "lamningsnummer": r["lamn"],
                "label": "",
                "certainty": "",
                "note": "",
                "band": band,
                "score": round(r["score"], 2),
                "percentile": pct,
                "name": r["name"] or "",
                "class": r["dominant_class"] or "",
                "n_sites": r["n_sites"],
                "municipality": r["municipality"] or "",
                "parish": r["parish"] or "",
                "lat": round(r["lat"], 6),
                "lon": round(r["lon"], 6),
                "road_m": (int(road_dist(r)) if road_dist(r) is not None else ""),
                "way_m": int(r["dist_to_way_m"]) if r["dist_to_way_m"] is not None else "",
                "board_m": int(r["dist_to_board_m"]) if r["dist_to_board_m"] is not None else "",
                "description": desc,
                "fornsok": f"https://app.raa.se/open/fornsok/lamning/{r['uuid']}",
                "maps": f"https://www.google.com/maps/search/?api=1&query={r['lat']:.6f},{r['lon']:.6f}",
            })
            seen.add(r["lamn"])
    return out


def merge(path, hand):
    """Append filled rows (label 0 or 1) from a review CSV into hand_labels.csv."""
    if not os.path.exists(path):
        sys.exit(f"{path} not found")
    seen = already_labelled(hand)
    added = skipped = 0
    lines = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lamn = (row.get("lamningsnummer") or "").strip()
            lab = (row.get("label") or "").strip()
            if not lamn or lab not in ("0", "1"):
                skipped += 1
                continue
            if lamn in seen:
                skipped += 1
                continue
            note = (row.get("note") or "").strip() or \
                   f"{row.get('band','')} review, {row.get('class','')}"
            cert = (row.get("certainty") or "").strip() or "2"
            if cert not in ("1", "2", "3"):
                cert = "2"
            lines.append(f'{lamn},{lab},{cert},"{note}"\n')
            seen.add(lamn)
            added += 1
    if lines:
        with open(hand, "a", encoding="utf-8") as f:
            f.writelines(lines)
    print(f"merged {added} labels into {hand} ({skipped} skipped: blank or duplicate)")
    if added:
        print("now re-run:  ./run_pipeline.sh --from 3")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB)
    p.add_argument("--n", type=int, default=20, help="total rows (split across bands)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default=None)
    p.add_argument("--hand", default=HAND)
    p.add_argument("--merge", metavar="CSV",
                   help="merge a filled review CSV into hand_labels.csv and exit")
    p.add_argument("--near-road", type=float, default=None, metavar="M",
                   help="only sample clusters within M metres of a DRIVABLE road, "
                        "so signage can be checked in Street View from a desk. "
                        "Note the target being labelled is 'has a sign', which is "
                        "NOT the same target as the automatic labels (which "
                        "measure documentation)")
    p.add_argument("--ways", default=WAYS)
    p.add_argument("--roads", choices=tuple(ROAD_SETS), default="drivable",
                   help="'major' = numbered public roads only, where Street View "
                        "coverage is near-complete")
    p.add_argument("--minimal", action="store_true",
                   help="emit only id + Fornsok link + Google Maps link")
    args = p.parse_args()

    if args.merge:
        merge(args.merge, args.hand)
        return

    if not os.path.exists(args.db):
        sys.exit(f"missing {args.db} — run ./run_pipeline.sh first")

    per = max(1, args.n // len(BANDS))
    grid = None
    if args.near_road is not None:
        if not os.path.exists(args.ways):
            sys.exit(f"missing {args.ways}")
        print(f"building road index ({args.roads})...")
        grid = drivable_road_grid(args.ways, ROAD_SETS[args.roads])

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = fetch(conn, per, already_labelled(args.hand), random.Random(args.seed),
                 road_grid=grid, max_road=args.near_road)
    conn.close()

    out = args.out or f"review_{time.strftime('%Y%m%d')}.csv"
    fields = ["lamningsnummer", "fornsok", "maps"] if args.minimal else FIELDS
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    if args.minimal:
        for r in rows:
            print(f"{r['lamningsnummer']}\t{r['fornsok']}\t{r['maps']}")

    print(f"\nwrote {len(rows)} rows to {out}  ({per} per band)")
    for band, desc in BANDS:
        print(f"  {band:<10} {desc}")
    print("""
Fill THREE columns:

`label` -- graded interest, and the states matter:
  1      signposted, or clearly worth the trip
  0.5    no sign, but something is visibly there
  0      clear view and nothing to see  <-- a VERIFIED NEGATIVE, the scarcest
         data here
  blank  could not verify (no Street View facing it, private property, no photos)

Do not use blank for "no sign". Blank means "unknown", and if verified negatives
end up blank we are back to a positives-only label set, which is the whole
problem this sample exists to fix.

`certainty` -- how sure are you? Street View is rarely conclusive, so a hunch
should not carry the same weight as a clear look:
  3  certain (stood right in front of it, no doubt)
  2  fairly sure (default if left blank)
  1  just an impression

`note` -- free text. Worth recording what the sign said, or why the view was
inconclusive.
""")
    print("Then:")
    print(f"  python3 sample_for_review.py --merge {out}")


if __name__ == "__main__":
    main()
