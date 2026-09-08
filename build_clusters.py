#!/usr/bin/env python3
"""
Stage 3: group sites into visitable destinations.

A visitor cares about a *place*, not a database record: a gravfalt of 40
stensattningar sharing one signpost is one destination. Clustering before
scoring keeps signals from being counted 40 times.

Grouping strategy, in order of authority:

1. RAA-nummer prefix, qualified by parish. "Askim 268:1" and "Askim 268:2" are
   sub-parts of one registered site. The prefix ALONE is unsafe: parish names
   repeat across Sweden, and bare "Karl Gustav 56" spans two parishes 1,008 km
   apart. The key is therefore (parish_code, raa_group).
2. A spatial guard splits any RAA group whose members are still far apart, so a
   stale or mis-keyed record cannot drag a cluster across the map.
3. Sites with no usable RAA-nummer fall back to single-link spatial clustering
   restricted to the same class, so a charcoal pit is never merged into a
   burial mound.

Reads:  src/data/sites.sqlite
Writes: src/data/sites.sqlite  (tables `clusters` and `site_clusters`)

Usage:
    python build_clusters.py
    python build_clusters.py --raa-split 500 --fallback-radius 150
"""

import argparse
import collections
import json
import math
import sqlite3
import sys
import time

DB = "src/data/sites.sqlite"


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def single_link(items, radius):
    """Single-link clustering on (key, e, n) via a grid. Returns key -> group id.

    Coordinates are SWEREF99 TM metres, so plain Euclidean distance is correct --
    no haversine, no cosine-latitude correction.
    """
    uf = UnionFind()
    grid = collections.defaultdict(list)
    cell = radius
    for key, e, n in items:
        uf.find(key)
        grid[(int(e // cell), int(n // cell))].append((key, e, n))

    r2 = radius * radius
    for (cx, cy), bucket in grid.items():
        # Compare each cell against itself and its 8 neighbours only.
        neighbours = [
            p
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for p in grid.get((cx + dx, cy + dy), ())
        ]
        for k1, e1, n1 in bucket:
            for k2, e2, n2 in neighbours:
                if k1 == k2:
                    continue
                if (e1 - e2) ** 2 + (n1 - n2) ** 2 <= r2:
                    uf.union(k1, k2)
    return {k: uf.find(k) for k, _, _ in items}


SCHEMA = """
DROP TABLE IF EXISTS clusters;
DROP TABLE IF EXISTS site_clusters;

CREATE TABLE clusters (
    cluster_id     TEXT PRIMARY KEY,
    method         TEXT,      -- 'raa' | 'spatial' | 'singleton'
    n_sites        INTEGER,
    dominant_class TEXT,
    n_classes      INTEGER,
    class_mix      TEXT,
    name           TEXT,      -- representative folk name, if any
    has_name       INTEGER,
    raa_group      TEXT,
    parish         TEXT, parish_code TEXT,
    municipality   TEXT, municipality_code TEXT,
    county         TEXT, province TEXT,
    centroid_e     REAL, centroid_n REAL,
    lon            REAL, lat REAL,
    spread_m       REAL,      -- max distance between members
    bbox_w_m       REAL, bbox_h_m REAL,
    any_polygon    INTEGER,
    any_visible    INTEGER,
    geom_types     TEXT,
    best_description      TEXT,
    best_description_len  INTEGER,
    all_boilerplate       INTEGER,
    any_measurements      INTEGER
);

CREATE TABLE site_clusters (
    uuid       TEXT PRIMARY KEY,
    cluster_id TEXT NOT NULL
);
"""

INDEXES = """
CREATE INDEX idx_sc_cluster    ON site_clusters(cluster_id);
CREATE INDEX idx_cl_class      ON clusters(dominant_class);
CREATE INDEX idx_cl_n          ON clusters(n_sites);
CREATE INDEX idx_cl_lonlat     ON clusters(lon, lat);
CREATE INDEX idx_cl_muni       ON clusters(municipality_code);
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB)
    p.add_argument("--raa-split", type=float, default=500.0,
                   help="split an RAA group if members exceed this distance (m)")
    p.add_argument("--fallback-radius", type=float, default=150.0,
                   help="single-link radius for sites without an RAA-nummer (m)")
    p.add_argument("--progress-json", action="store_true")
    args = p.parse_args()
    J = args.progress_json

    def emit(**kw):
        if J:
            sys.stdout.write(json.dumps(kw) + "\n"); sys.stdout.flush()
        elif kw.get("message"):
            print(kw["message"])

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT uuid, raa_group, parish_code, class_sv, centroid_e, centroid_n "
        "FROM sites"
    ).fetchall()
    emit(event="stage", name="cluster", total=len(rows),
         message=f"Clustering {len(rows):,} sites...")
    t0 = time.time()

    # --- pass 1: RAA groups, qualified by parish -------------------------- #
    raa_members = collections.defaultdict(list)
    ungrouped = []
    for r in rows:
        if r["raa_group"] and r["parish_code"] and r["centroid_e"] is not None:
            raa_members[(r["parish_code"], r["raa_group"])].append(r)
        else:
            ungrouped.append(r)

    assign = {}
    method = {}
    split_count = 0
    for (pcode, group), members in raa_members.items():
        base = f"raa:{pcode}:{group}"
        if len(members) == 1:
            assign[members[0]["uuid"]] = base
            method[base] = "raa"
            continue
        # Spatial guard: split a group whose members are not actually together.
        sub = single_link(
            [(m["uuid"], m["centroid_e"], m["centroid_n"]) for m in members],
            args.raa_split,
        )
        roots = {}
        for uuid, root in sub.items():
            roots.setdefault(root, len(roots))
        if len(roots) > 1:
            split_count += 1
        for uuid, root in sub.items():
            idx = roots[root]
            cid = base if len(roots) == 1 else f"{base}#{idx}"
            assign[uuid] = cid
            method[cid] = "raa"

    # --- pass 2: spatial fallback, same class only ------------------------ #
    by_class = collections.defaultdict(list)
    singletons = []
    for r in ungrouped:
        if r["centroid_e"] is None:
            singletons.append(r)
        else:
            by_class[r["class_sv"] or "?"].append(r)

    for cls, members in by_class.items():
        sub = single_link(
            [(m["uuid"], m["centroid_e"], m["centroid_n"]) for m in members],
            args.fallback_radius,
        )
        for uuid, root in sub.items():
            cid = f"sp:{root}"
            assign[uuid] = cid
            method[cid] = "spatial"
    for r in singletons:
        cid = f"one:{r['uuid']}"
        assign[r["uuid"]] = cid
        method[cid] = "singleton"

    emit(event="progress", stage="assigned", clusters=len(set(assign.values())),
         raa_groups_split=split_count,
         message=f"  {len(set(assign.values())):,} clusters "
                 f"({split_count:,} RAA groups split by the spatial guard)")

    # --- aggregate --------------------------------------------------------- #
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO site_clusters (uuid, cluster_id) VALUES (?, ?)",
        list(assign.items()),
    )
    conn.commit()

    conn.execute("CREATE INDEX idx_sc_tmp ON site_clusters(cluster_id)")
    agg = conn.execute("""
        SELECT sc.cluster_id,
               COUNT(*)                                  AS n_sites,
               COUNT(DISTINCT s.class_sv)                 AS n_classes,
               MAX(s.title)                               AS name,
               MAX(s.has_name)                            AS has_name,
               MAX(s.raa_group)                           AS raa_group,
               MAX(s.parish) AS parish, MAX(s.parish_code) AS parish_code,
               MAX(s.municipality) AS municipality,
               MAX(s.municipality_code) AS municipality_code,
               MAX(s.county) AS county, MAX(s.province) AS province,
               AVG(s.centroid_e) AS ce, AVG(s.centroid_n) AS cn,
               AVG(s.lon) AS lon, AVG(s.lat) AS lat,
               MIN(s.centroid_e) AS mine, MAX(s.centroid_e) AS maxe,
               MIN(s.centroid_n) AS minn, MAX(s.centroid_n) AS maxn,
               MAX(s.has_polygon) AS any_polygon,
               MAX(s.placering = 'Synlig ovan mark') AS any_visible,
               MIN(s.beskrivning_is_boilerplate) AS all_boiler,
               MAX(s.has_measurements) AS any_measure,
               MAX(s.description_len) AS best_len
        FROM site_clusters sc JOIN sites s ON s.uuid = sc.uuid
        GROUP BY sc.cluster_id
    """).fetchall()

    # class mix and the longest description need a second pass per cluster
    mix = collections.defaultdict(collections.Counter)
    geom = collections.defaultdict(set)
    for cid, cls, gt in conn.execute(
        "SELECT sc.cluster_id, s.class_sv, s.geom_types FROM site_clusters sc "
        "JOIN sites s ON s.uuid = sc.uuid"
    ):
        mix[cid][cls or "?"] += 1
        if gt:
            geom[cid].update(gt)

    best = {}
    for cid, d in conn.execute("""
        SELECT sc.cluster_id, s.beskrivning FROM site_clusters sc
        JOIN sites s ON s.uuid = sc.uuid
        WHERE s.beskrivning IS NOT NULL
    """):
        if d and len(d) > len(best.get(cid, "")):
            best[cid] = d

    out = []
    for r in agg:
        cid = r["cluster_id"]
        c = mix[cid]
        spread = math.hypot(r["maxe"] - r["mine"], r["maxn"] - r["minn"]) \
            if r["mine"] is not None else None
        out.append((
            cid, method.get(cid, "raa"), r["n_sites"],
            c.most_common(1)[0][0] if c else None, r["n_classes"],
            "; ".join(f"{k}×{v}" for k, v in c.most_common(4)),
            r["name"], r["has_name"], r["raa_group"],
            r["parish"], r["parish_code"], r["municipality"],
            r["municipality_code"], r["county"], r["province"],
            r["ce"], r["cn"], r["lon"], r["lat"], spread,
            (r["maxe"] - r["mine"]) if r["mine"] is not None else None,
            (r["maxn"] - r["minn"]) if r["minn"] is not None else None,
            r["any_polygon"], r["any_visible"],
            "".join(sorted(geom[cid])) or None,
            best.get(cid), len(best.get(cid, "")) or 0,
            r["all_boiler"], r["any_measure"],
        ))

    conn.executemany(
        f"INSERT INTO clusters VALUES ({','.join('?'*29)})", out
    )
    conn.execute("DROP INDEX IF EXISTS idx_sc_tmp")
    conn.executescript(INDEXES)
    conn.commit()

    n = conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
    emit(event="done", name="cluster", clusters=n, sites=len(rows),
         seconds=round(time.time() - t0, 1),
         message=f"Wrote {n:,} clusters from {len(rows):,} sites "
                 f"in {time.time()-t0:.0f}s")
    conn.close()


if __name__ == "__main__":
    main()
