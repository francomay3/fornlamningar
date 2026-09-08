#!/usr/bin/env python3
"""
Export scored clusters as tippecanoe vector tiles for the frontend.

The frontend lives in a separate repo (franco-may, Next.js + MapLibre) and
already reads tippecanoe tiles. This reproduces the contract its existing tiles
declare in metadata.json:

    layer:  archaeological_sites
    fields: uuid, label, class, description, score
            (clustered / point_count / sqrt_point_count are added by tippecanoe)

`score` is consumed by the frontend only as a MapLibre `symbol-sort-key`, so
only the ordering matters. We emit a 0-100 percentile because it is readable
when debugging.

One feature per CLUSTER, not per site: a gravfalt of 40 stensattningar is one
place a visitor drives to, and should be one pin.

Reads:  src/data/sites.sqlite
Writes: the --out directory (defaults to the frontend repo)

Usage:
    python build_tiles.py --out /tmp/tiles-test      # dry run somewhere safe
    python build_tiles.py                            # straight into franco-may
    python build_tiles.py --max-desc 0                # full descriptions
    python build_tiles.py --score full                # rank known places higher
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

DB = "src/data/sites.sqlite"
DEFAULT_OUT = os.path.expanduser("~/projects/franco-may/public/tiles")
GEOJSON = "src/data/tiles_input.geojsonl"
LAYER = "archaeological_sites"

# Matches the options recorded in the frontend's existing metadata.json, so the
# map keeps behaving the same way.
TIPPECANOE_OPTS = [
    # maxzoom 14, NOT `-zg`. With `-zg` tippecanoe picked maxzoom 9, and
    # `--cluster-densest-as-needed` merges nearby points at low zoom and places
    # the merged feature at the AVERAGE position -- Hunehals borg landed 595 m
    # from its true location with point_count=2. Because MapLibre overzooms the
    # deepest tile it has, that displacement then persists at EVERY zoom level.
    # At z14 features are unclustered and positions are exact to well under a
    # metre, while clustering still declutters the low zooms.
    "-z14", "-Z0", "--force", "--preserve-input-order",
    # Disable the default gamma rate-thinning (--drop-rate 2.5). It dropped
    # 9,999 of 10,000 features at z0-z9 -- the map went blank on zoom out --
    # and it chose WHICH to drop by nothing but arrival order spacing, so the
    # single survivor was not even a notable site. We decide visibility
    # ourselves in assign_minzoom() and hand tippecanoe a per-feature
    # tippecanoe.minzoom, which it always honours.
    "--drop-rate=1",
    # Kept only as a tile-size safety net. It merges nearby points and places
    # the merged feature at their AVERAGE position, which is why maxzoom must
    # stay 14: at z14 nothing clusters and positions are exact to under a
    # metre. (With `-zg` tippecanoe picked maxzoom 9, Hunehals borg landed
    # 595 m off, and MapLibre overzooms the deepest tile, so that displacement
    # then persisted at every zoom.)
    "--cluster-densest-as-needed", "--extend-zooms-if-still-dropping",
    "--cluster-distance=5",
    # Tiles served as plain static files from Next.js `public/` arrive without a
    # Content-Encoding header, so MapLibre cannot know they are gzipped and
    # fails with "Unable to parse the tile". Write them raw instead: a .pbf must
    # start with protobuf bytes (1a86...), not the gzip magic (1f8b...).
    "--no-tile-compression",
]


def one_line(text, limit):
    """RAA descriptions are hard-wrapped mid-word; collapse to one line."""
    if not text:
        return ""
    t = " ".join(text.split())
    if limit and len(t) > limit:
        return t[:limit].rsplit(" ", 1)[0] + "…"
    return t


# Points per tile edge used as the thinning grid. Each tile is cut into
# CELLS_PER_TILE^2 cells and at most one point per cell may appear at that
# zoom, so density is bounded everywhere while coverage stays even -- a
# national top-N instead would leave whole regions blank at mid zooms.
# 24 puts cells ~21 px apart (512/24), which is about the tightest spacing at
# which map pins stay distinguishable. 12 was visibly too sparse when zooming
# out; 8 emptied the regional zooms again.
CELLS_PER_TILE = 24


def assign_minzoom(rows, maxzoom, cells_per_tile=CELLS_PER_TILE):
    """Give every row the lowest zoom at which it can be shown.

    Greedy, best-first: walking zooms from the top down, a point becomes
    visible at the first zoom where no better-scoring point has already taken
    its grid cell. `rows` must already be sorted best-first.

    The result is that zooming out never empties the map -- it only thins it,
    and what survives is the best thing in each area rather than an arbitrary
    sample.
    """
    import math

    xy = []
    for r in rows:
        lon, lat = r["lon"], r["lat"]
        x = (lon + 180.0) / 360.0
        # Web-mercator y, clamped off the poles where the projection diverges.
        s = math.sin(math.radians(max(-85.05, min(85.05, lat))))
        y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
        xy.append((x, y))

    minzoom = [maxzoom] * len(rows)
    for z in range(maxzoom + 1):
        n = (1 << z) * cells_per_tile
        taken = set()
        for i, (x, y) in enumerate(xy):
            if minzoom[i] < z:
                continue          # already visible at a lower zoom
            cell = (int(x * n), int(y * n))
            if cell in taken:
                continue          # a better point owns this cell at this zoom
            taken.add(cell)
            minzoom[i] = z
    return minzoom


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB)
    p.add_argument("--out", default=DEFAULT_OUT, help="tile output directory")
    p.add_argument("--geojson", default=GEOJSON)
    p.add_argument("--score", choices=("intrinsic", "full"), default="intrinsic",
                   help="intrinsic = discovery (ignores existing documentation); "
                        "full = also credits Wikipedia/photos")
    p.add_argument("--max-desc", type=int, default=280,
                   help="truncate descriptions; 0 keeps full text. This text "
                        "ships inside the tiles and dominates their size")
    p.add_argument("--include-excluded", action="store_true",
                   help="also emit blacklisted / soft-excluded clusters")
    p.add_argument("--min-score", type=float, default=None,
                   help="drop clusters below this raw score")
    p.add_argument("--top", type=int, default=None,
                   help="keep only the N best-scoring clusters. Ranking happens "
                        "over ALL clusters first, so the cut is national, not "
                        "per-region")
    p.add_argument("--maxzoom", type=int, default=14,
                   help="must match the -z in TIPPECANOE_OPTS")
    p.add_argument("--cells-per-tile", type=int, default=CELLS_PER_TILE,
                   help="thinning grid resolution; higher = denser low zooms")
    p.add_argument("--keep-geojson", action="store_true")
    p.add_argument("--skip-tippecanoe", action="store_true")
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"missing {args.db} - run ./run_pipeline.sh first")
    if not args.skip_tippecanoe and not shutil.which("tippecanoe"):
        sys.exit("tippecanoe not found (brew install tippecanoe)")

    score_col = f"sc.score_{args.score}"
    where = ["c.lon IS NOT NULL"]
    if not args.include_excluded:
        where += ["sc.excluded_hard = 0", "sc.excluded_soft = 0"]
    if args.min_score is not None:
        where.append(f"{score_col} >= {args.min_score}")

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"""
        SELECT c.cluster_id, c.name, c.dominant_class, c.n_sites,
               c.lon, c.lat, c.best_description,
               {score_col} AS score,
               (SELECT s.uuid FROM site_clusters x
                  JOIN sites s ON s.uuid = x.uuid
                 WHERE x.cluster_id = c.cluster_id
                 ORDER BY s.description_len DESC, s.uuid LIMIT 1) AS uuid
        FROM clusters c
        JOIN scores sc ON sc.cluster_id = c.cluster_id
        WHERE {' AND '.join(where)}
        ORDER BY {score_col} DESC
        {f'LIMIT {args.top}' if args.top else ''}
    """).fetchall()
    conn.close()

    if not rows:
        sys.exit("no clusters matched the filters")
    n = len(rows)
    print(f"exporting {n:,} clusters"
          + (f" (top {args.top:,})" if args.top else "")
          + f" (score_{args.score}, desc limit {args.max_desc or 'none'})")
    if args.top:
        print(f"  score range kept: {rows[0]['score']:.2f} .. {rows[-1]['score']:.2f}")

    minzoom = assign_minzoom(rows, args.maxzoom, args.cells_per_tile)
    hist = {}
    for z in minzoom:
        hist[z] = hist.get(z, 0) + 1
    cum = 0
    shown = []
    for z in sorted(hist):
        cum += hist[z]
        shown.append(f"z{z}:{cum:,}")
    print("  visible by zoom (cumulative): " + "  ".join(shown))

    os.makedirs(os.path.dirname(args.geojson) or ".", exist_ok=True)
    t0 = time.time()
    named = 0
    with open(args.geojson, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            cls = r["dominant_class"] or ""
            if r["name"]:
                label = r["name"]
                named += 1
            elif (r["n_sites"] or 1) > 1:
                label = f"{cls} ({r['n_sites']})"   # e.g. "Gravfalt (12)"
            else:
                label = cls or "Fornlamning"
            f.write(json.dumps({
                "type": "Feature",
                "geometry": {"type": "Point",
                             "coordinates": [round(r["lon"], 6),
                                             round(r["lat"], 6)]},
                "properties": {
                    "uuid": r["uuid"] or "",
                    "label": label,
                    "class": cls,
                    "description": one_line(r["best_description"], args.max_desc),
                    # Percentile, best-first. Ordering is all the frontend uses.
                    "score": round(100.0 * (n - i) / n, 2),
                },
                "tippecanoe": {"minzoom": minzoom[i]},
            }, ensure_ascii=False) + "\n")
    gj = os.path.getsize(args.geojson) / 1e6
    print(f"  geojsonl {gj:.1f} MB, {named:,} with a folk name "
          f"({time.time()-t0:.0f}s)")

    if args.skip_tippecanoe:
        print(f"  kept {args.geojson}")
        return

    out = os.path.expanduser(args.out)
    os.makedirs(out, exist_ok=True)
    cmd = ["tippecanoe", *TIPPECANOE_OPTS, "-l", LAYER, "-e", out, args.geojson]
    print("  " + " ".join(cmd))
    subprocess.run(cmd, check=True)

    total = sum(os.path.getsize(os.path.join(d, fn))
                for d, _, fs in os.walk(out) for fn in fs)
    tiles = sum(len([f for f in fs if f.endswith(".pbf")])
                for _, _, fs in os.walk(out))
    print(f"\n{tiles:,} tiles, {total/1e6:.1f} MB -> {out}")
    if not args.keep_geojson:
        os.remove(args.geojson)


if __name__ == "__main__":
    main()
