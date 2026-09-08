#!/usr/bin/env python3
"""
Stage 4: assemble the signals table.

One row per cluster, holding RAW MEASUREMENTS -- never points or weights.
Scoring is a query-time expression over this table, so re-tuning never requires
re-deriving anything.

Spatial signals come from the OSM extract. Two measurements matter:

  * dist_to_way_m   -- distance to the nearest OSM `highway` of ANY kind,
                       roads and trails together. Measured at 2.61x
                       discrimination on a Falkoping sample; trails alone were
                       only 2.05x, and splitting them would penalise sites that
                       are legitimately trail-access-only.
  * dist_to_board_m -- distance to the nearest `tourism=information` node.
                       Strong positive evidence of a curated, signposted site.
                       Weak *negative* evidence: OSM board coverage tracks
                       mapper density, so absence proves little.

All distance maths is in SWEREF99 TM (EPSG:3006) where coordinates are already
metres -- no haversine, no cosine-latitude correction.

Reads:  src/data/sites.sqlite            (sites, clusters, site_clusters, wikidata)
        src/data/osm/sweden_ways.gpkg    (highway lines, SWEREF99)
        src/data/osm/boards.gpkg         (tourism=information nodes, SWEREF99)
Writes: src/data/sites.sqlite            (table `signals`)

Usage:
    python build_signals.py
    python build_signals.py --skip-spatial   # intrinsic signals only
"""

import argparse
import json
import os
import sqlite3
import struct
import sys
import time

import numpy as np

DB = "src/data/sites.sqlite"
WAYS_GPKG = "src/data/osm/sweden_ways.gpkg"
BOARDS_GPKG = "src/data/osm/boards.gpkg"
ARCH_GPKG = "src/data/osm/historic_pt.gpkg"
ARCH_POLY_GPKG = "src/data/osm/historic_poly.gpkg"
BUILDINGS_GPKG = "src/data/osm/buildings.gpkg"

# Roads a car can use, as opposed to `dist_to_way_m` which is the union of ALL
# ways including footpaths. Different question: "can I park near it?" rather
# than "can I reach it on foot?".
DRIVABLE = {
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link", "unclassified", "residential",
    "living_street",
}

CELL = 500.0          # metres; grid cell for candidate lookup
DENSIFY = 20.0        # metres; max spacing along a way, bounds nearest-point error
MAX_SEARCH = 5000.0   # metres; give up beyond this and record NULL

# Classes with no visible surface expression worth travelling for. Derived from
# per-class notability AND photograph lift, both near zero for these.
CLASS_BLACKLIST = {
    "Kolningsanläggning", "Härd", "Fångstgrop", "Fångstgropssystem",
    "Kokgrop", "Boplatsgrop", "Boplats", "Boplatslämning övrig",
    "Boplatsvall", "Skärvstenshög", "Fossil åkermark",
    "Område med fossil åkermark", "Kemisk industri", "Förvaringsanläggning",
    "Område med skogsbrukslämningar",
}
# Weak on its own (0.26x photograph lift) but 29.6% of the dataset and it does
# contain good sites. Excluded by default, rescued by any positive evidence.
CLASS_SOFT_BLACKLIST = {"Stensättning"}


def class_significance(conn):
    """Smoothed positive rate per class, measured from the labels table.

    Used to pick which class REPRESENTS a mixed cluster. The previous rule --
    most frequent class -- mislabelled mixed clusters, and the first fix fell
    back to alphabetical order, which is arbitrary. Ranking by measured
    significance means a `Gravfalt` sharing an RAA number with a `Skarvstenshog`
    identifies the cluster as a grave field, which is what a visitor sees.
    """
    tot = conn.execute("SELECT COUNT(*) FROM sites").fetchone()[0]
    npos = conn.execute(
        "SELECT COUNT(*) FROM labels WHERE label > 0").fetchone()[0]
    base = (npos / tot) if tot else 0.0
    rates = {}
    for cls, n, k in conn.execute("""
            SELECT s.class_sv, COUNT(*),
                   SUM(CASE WHEN l.uuid IS NOT NULL THEN 1 ELSE 0 END)
            FROM sites s
            LEFT JOIN labels l ON l.uuid = s.uuid AND l.label > 0
            GROUP BY s.class_sv"""):
        if not cls:
            continue
        rates[cls] = (k + 60.0 * base) / (n + 60.0)   # same smoothing as scoring
    return rates, base


# --------------------------------------------------------------------------- #
# GeoPackage geometry reading
# --------------------------------------------------------------------------- #

def gpkg_envelope(blob):
    """(minx,maxx,miny,maxy) from a GeoPackage header, or None."""
    if not blob or len(blob) < 40 or ((blob[3] >> 1) & 0x07) != 1:
        return None
    return struct.unpack("<4d", blob[8:40])


def gpkg_wkb(blob):
    """Strip the GeoPackage binary header, returning the bare WKB."""
    flags = blob[3]
    env = (flags >> 1) & 0x07
    env_size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(env, 0)
    return blob[8 + env_size:]


def wkb_linestring_points(wkb):
    """Vertices of a WKB LineString (or the parts of a MultiLineString)."""
    order = "<" if wkb[0] == 1 else ">"
    gtype = struct.unpack(order + "I", wkb[1:5])[0] % 1000
    if gtype == 2:  # LineString
        n = struct.unpack(order + "I", wkb[5:9])[0]
        if n < 2:
            return []
        arr = np.frombuffer(wkb[9:9 + 16 * n], dtype=np.dtype(
            (">" if order == ">" else "<") + "f8"))
        return [arr.reshape(n, 2)]
    if gtype == 5:  # MultiLineString
        cnt = struct.unpack(order + "I", wkb[5:9])[0]
        out, off = [], 9
        for _ in range(cnt):
            o2 = "<" if wkb[off] == 1 else ">"
            n = struct.unpack(o2 + "I", wkb[off + 5:off + 9])[0]
            start = off + 9
            if n >= 2:
                arr = np.frombuffer(wkb[start:start + 16 * n],
                                    dtype=np.dtype(("<" if o2 == "<" else ">") + "f8"))
                out.append(arr.reshape(n, 2))
            off = start + 16 * n
        return out
    return []


def wkb_point(wkb):
    order = "<" if wkb[0] == 1 else ">"
    gtype = struct.unpack(order + "I", wkb[1:5])[0] % 1000
    if gtype != 1:
        return None
    return struct.unpack(order + "2d", wkb[5:21])


def densify(pts, spacing=DENSIFY):
    """Insert points along each segment so spacing never exceeds `spacing`.

    Bounds the nearest-*vertex* error to half the spacing, which lets us avoid
    exact point-to-segment maths without meaningfully losing accuracy.
    """
    a, b = pts[:-1], pts[1:]
    seg = b - a
    length = np.hypot(seg[:, 0], seg[:, 1])
    keep = length > 0
    if not keep.any():
        return pts[:1]
    a, seg, length = a[keep], seg[keep], length[keep]
    steps = np.ceil(length / spacing).astype(np.int64)
    total = int(steps.sum())
    # Fully vectorised: expand each segment into `steps` interpolated points
    # without a per-segment Python loop (there are ~23M segments nationally).
    idx = np.repeat(np.arange(len(a)), steps)
    offs = np.repeat(np.cumsum(steps) - steps, steps)
    t = (np.arange(total, dtype=np.float64) - offs) / steps[idx]
    out = np.empty((total + 1, 2), dtype=np.float64)
    out[:total] = a[idx] + seg[idx] * t[:, None]
    out[total] = pts[-1]
    return out


# --------------------------------------------------------------------------- #
# grid index over a point cloud
# --------------------------------------------------------------------------- #

class PointGrid:
    """Nearest-point queries over millions of points, via a sorted cell index."""

    def __init__(self, e, n, cell=CELL):
        self.cell = cell
        self.e = e.astype(np.int32)
        self.n = n.astype(np.int32)
        cx = np.floor(e / cell).astype(np.int64)
        cy = np.floor(n / cell).astype(np.int64)
        self.key = cx * 100_000 + cy
        order = np.argsort(self.key, kind="stable")
        self.e, self.n, self.key = self.e[order], self.n[order], self.key[order]
        uniq, start = np.unique(self.key, return_index=True)
        self.uniq = uniq
        self.start = start
        self.end = np.append(start[1:], len(self.key))

    def _range(self, k):
        i = np.searchsorted(self.uniq, k)
        if i < len(self.uniq) and self.uniq[i] == k:
            return self.start[i], self.end[i]
        return None

    def nearest(self, qe, qn, max_search=MAX_SEARCH):
        cx, cy = int(qe // self.cell), int(qn // self.cell)
        ring = 0
        best = None
        while True:
            cand_e, cand_n = [], []
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if ring and max(abs(dx), abs(dy)) != ring:
                        continue  # only the new outer ring
                    r = self._range((cx + dx) * 100_000 + (cy + dy))
                    if r:
                        cand_e.append(self.e[r[0]:r[1]])
                        cand_n.append(self.n[r[0]:r[1]])
            if cand_e:
                ce = np.concatenate(cand_e).astype(np.float64) - qe
                cn = np.concatenate(cand_n).astype(np.float64) - qn
                d = float(np.sqrt((ce * ce + cn * cn).min()))
                best = d if best is None else min(best, d)
            # A hit inside the searched radius is final; otherwise widen.
            if best is not None and best <= ring * self.cell:
                return best
            ring += 1
            if ring * self.cell > max_search:
                return best


def load_ways(path, classes=None):
    """Densified points along every way, or only the given highway classes."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    chunks = []
    t0 = time.time()
    n_ways = 0
    sql = ("SELECT highway, geom FROM ways WHERE geom IS NOT NULL"
           if classes else "SELECT NULL, geom FROM ways WHERE geom IS NOT NULL")
    for highway, blob in conn.execute(sql):
        if classes and highway not in classes:
            continue
        for pts in wkb_linestring_points(gpkg_wkb(blob)):
            chunks.append(densify(pts))
            n_ways += 1
    conn.close()
    allp = np.concatenate(chunks)
    print(f"  {n_ways:,} way parts -> {len(allp):,} densified points "
          f"in {time.time()-t0:.0f}s")
    return allp


def load_building_centroids(path):
    """Centroid of every building, from its GeoPackage envelope header.

    Buildings are small, so the envelope centre is within a few metres of the
    true nearest point -- accurate enough to tell "inside somebody's garden"
    from "out in the forest", which is what the allemansratten distinction
    hinges on: in Sweden you may walk almost anywhere EXCEPT a house plot.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out = []
    for (blob,) in conn.execute("SELECT geom FROM b WHERE geom IS NOT NULL"):
        e = gpkg_envelope(blob)
        if e:
            out.append(((e[0] + e[1]) / 2, (e[2] + e[3]) / 2))
    conn.close()
    return np.array(out) if out else np.zeros((0, 2))


def load_points(path, layer):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out = []
    for (blob,) in conn.execute(f'SELECT geom FROM "{layer}" WHERE geom IS NOT NULL'):
        p = wkb_point(gpkg_wkb(blob))
        if p:
            out.append(p)
    conn.close()
    return np.array(out) if out else np.zeros((0, 2))


SCHEMA = """
DROP TABLE IF EXISTS signals;
CREATE TABLE signals (
    cluster_id TEXT PRIMARY KEY,
    n_sites INTEGER,
    dominant_class TEXT,
    class_blacklisted INTEGER,
    class_soft_blacklisted INTEGER,
    has_name INTEGER,
    geom_type_count INTEGER,
    has_polygon INTEGER,
    env_area_m2 REAL,
    dim_len_m REAL,
    dim_height_m REAL,
    dim_area_m2 REAL,
    best_description_len INTEGER,
    all_boilerplate INTEGER,
    any_measurements INTEGER,
    any_visible INTEGER,
    sitelinks INTEGER,
    has_image INTEGER,
    has_commons INTEGER,
    dist_to_way_m REAL,
    dist_to_board_m REAL,
    dist_to_osm_arch_m REAL,
    dist_to_road_m REAL,
    dist_to_building_m REAL,
    neighbors_1km INTEGER,
    spatial_checked_at TEXT,
    wikidata_checked_at TEXT
);
"""
INDEXES = """
CREATE INDEX idx_sig_class ON signals(dominant_class);
CREATE INDEX idx_sig_way   ON signals(dist_to_way_m);
CREATE INDEX idx_sig_board ON signals(dist_to_board_m);
CREATE INDEX idx_sig_name  ON signals(has_name);
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB)
    p.add_argument("--ways", default=WAYS_GPKG)
    p.add_argument("--boards", default=BOARDS_GPKG)
    p.add_argument("--arch", default=ARCH_GPKG)
    p.add_argument("--arch-poly", default=ARCH_POLY_GPKG)
    p.add_argument("--buildings", default=BUILDINGS_GPKG)
    p.add_argument("--skip-spatial", action="store_true")
    p.add_argument("--progress-json", action="store_true")
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    print("Aggregating per-cluster attributes...")
    rows = conn.execute("""
        SELECT c.cluster_id, c.n_sites, c.dominant_class, c.has_name,
               c.centroid_e, c.centroid_n, c.any_polygon, c.any_visible,
               c.best_description_len, c.all_boilerplate, c.any_measurements,
               MAX(s.geom_type_count) AS gtc,
               MAX(s.env_area_m2)     AS area,
               MAX(s.dim_len_m)       AS dim_len,
               MAX(s.dim_height_m)    AS dim_h,
               MAX(s.dim_area_m2)     AS dim_area,
               MAX(COALESCE(w.sitelinks,0)) AS sitelinks,
               MAX(CASE WHEN w.image IS NOT NULL THEN 1 ELSE 0 END) AS has_image,
               MAX(CASE WHEN w.commons_category IS NOT NULL THEN 1 ELSE 0 END) AS has_commons
        FROM clusters c
        JOIN site_clusters sc ON sc.cluster_id = c.cluster_id
        JOIN sites s          ON s.uuid = sc.uuid
        LEFT JOIN wikidata w  ON w.uuid = s.uuid
        GROUP BY c.cluster_id
    """).fetchall()
    print(f"  {len(rows):,} clusters")

    # Member classes per cluster. NOT via GROUP_CONCAT: RAA class names contain
    # commas ("Husgrund, historisk tid", "Ristning, medeltid/historisk tid"),
    # so splitting a comma-joined string shreds them into fragments that match
    # no real class at all.
    members = {}
    for cid, cls in conn.execute(
            "SELECT sc.cluster_id, s.class_sv FROM site_clusters sc "
            "JOIN sites s ON s.uuid = sc.uuid "
            "WHERE s.class_sv IS NOT NULL GROUP BY 1, 2"):
        members.setdefault(cid, set()).add(cls)

    sig, _base = class_significance(conn)
    print(f"  significancia medida para {len(sig):,} clases")

    # Second pass over NON-blacklisted members only. Cluster attributes are
    # aggregated with MAX() across members, so without this a charcoal pit
    # sharing an RAA number could supply the cluster's height, description or
    # name -- attributes of something the visitor is not going there to see.
    holes = ",".join("?" * len(CLASS_BLACKLIST))
    worthy_agg = {r["cluster_id"]: r for r in conn.execute(f"""
        SELECT sc.cluster_id,
               MAX(s.geom_type_count) AS gtc,
               MAX(s.env_area_m2)     AS area,
               MAX(s.dim_len_m)       AS dim_len,
               MAX(s.dim_height_m)    AS dim_h,
               MAX(s.dim_area_m2)     AS dim_area,
               MAX(s.description_len) AS best_len,
               MAX(s.has_name)        AS has_name,
               MAX(s.has_measurements) AS any_measure,
               MIN(s.beskrivning_is_boilerplate) AS all_boiler,
               MAX(s.placering = 'Synlig ovan mark') AS any_visible,
               MAX(s.has_polygon)     AS any_polygon
        FROM site_clusters sc JOIN sites s ON s.uuid = sc.uuid
        WHERE s.class_sv IS NULL OR s.class_sv NOT IN ({holes})
        GROUP BY sc.cluster_id
    """, tuple(CLASS_BLACKLIST))}
    print(f"  {len(worthy_agg):,} clusters con al menos un miembro no blacklisteado")

    way_grid = board_grid = arch_grid = road_grid = bldg_grid = None
    if not args.skip_spatial:
        if os.path.exists(args.ways):
            print("Loading OSM ways (all)...")
            wp = load_ways(args.ways)
            way_grid = PointGrid(wp[:, 0], wp[:, 1])
            del wp
            print("Loading drivable roads...")
            rp = load_ways(args.ways, DRIVABLE)
            road_grid = PointGrid(rp[:, 0], rp[:, 1])
            del rp
        else:
            print(f"  ! {args.ways} missing; dist_to_way_m will be NULL")
        if os.path.exists(args.boards):
            bp = load_points(args.boards, "boards")
            print(f"  {len(bp):,} information boards")
            if len(bp):
                board_grid = PointGrid(bp[:, 0], bp[:, 1])
        else:
            print(f"  ! {args.boards} missing; dist_to_board_m will be NULL")
        # OSM's own archaeological_site features. Present = strong evidence
        # (24.3x lift); absent = almost no information, same as boards.
        ap = []
        for path, kind in ((args.arch, "pt"), (args.arch_poly, "poly")):
            if not os.path.exists(path):
                continue
            cn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            for tags, blob in cn.execute(
                    "SELECT other_tags, geom FROM feat WHERE geom IS NOT NULL"):
                if "archaeological_site" not in (tags or ""):
                    continue
                if kind == "pt":
                    q = wkb_point(gpkg_wkb(blob))
                    if q:
                        ap.append(q)
                else:
                    e = gpkg_envelope(blob) if len(blob) >= 40 else None
                    if e:
                        ap.append(((e[0] + e[1]) / 2, (e[2] + e[3]) / 2))
            cn.close()
        if ap:
            a = np.array(ap)
            print(f"  {len(a):,} OSM archaeological_site features")
            arch_grid = PointGrid(a[:, 0], a[:, 1])
        if os.path.exists(args.buildings):
            bp = load_building_centroids(args.buildings)
            print(f"  {len(bp):,} building centroids")
            if len(bp):
                bldg_grid = PointGrid(bp[:, 0], bp[:, 1])
            del bp

    # cluster-density signal, computed on cluster centroids
    ce = np.array([r["centroid_e"] if r["centroid_e"] is not None else np.nan
                   for r in rows])
    cn = np.array([r["centroid_n"] if r["centroid_n"] is not None else np.nan
                   for r in rows])
    ok = ~np.isnan(ce)
    dens_grid = PointGrid(ce[ok], cn[ok], cell=1000.0)

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = []
    t0 = time.time()
    for i, r in enumerate(rows):
        e, n = r["centroid_e"], r["centroid_n"]
        dw = db = da = dr = dbl = None
        nb = None
        if e is not None:
            if way_grid:
                dw = way_grid.nearest(e, n)
            if board_grid:
                db = board_grid.nearest(e, n)
            if arch_grid:
                da = arch_grid.nearest(e, n)
            if road_grid:
                dr = road_grid.nearest(e, n)
            if bldg_grid:
                dbl = bldg_grid.nearest(e, n, max_search=2000.0)
            k = dens_grid._range(int(e // 1000.0) * 100_000 + int(n // 1000.0))
            nb = int(k[1] - k[0]) if k else 0
        # `dominant_class` from build_clusters is the most FREQUENT class, which
        # mislabels mixed clusters: Blomsholms gravfalt (240 m, ~40 monuments)
        # shared an RAA number with two fossil-field records, came out as
        # "Omrade med fossil akermark", and was blacklisted out of existence.
        # 982 clusters were being discarded this way.
        #
        # So: prefer a NON-blacklisted class when the cluster has one, and only
        # blacklist a cluster when every one of its classes is blacklisted --
        # i.e. when there is genuinely nothing there worth seeing.
        member = members.get(r["cluster_id"], set())
        worthy = member - CLASS_BLACKLIST
        # Represent the cluster by its most SIGNIFICANT class, not its most
        # frequent one, preferring classes that are not blacklisted.
        pool = worthy or member
        cls = (max(pool, key=lambda c: sig.get(c, 0.0)) if pool
               else r["dominant_class"])
        all_blacklisted = bool(member) and not worthy
        # Prefer attributes measured on the worthy members.
        wa = worthy_agg.get(r["cluster_id"])
        if wa is not None:
            r = {k: r[k] for k in r.keys()}
            for src, dst in (("gtc", "gtc"), ("area", "area"),
                             ("dim_len", "dim_len"), ("dim_h", "dim_h"),
                             ("dim_area", "dim_area"),
                             ("has_name", "has_name"),
                             ("any_measure", "any_measurements"),
                             ("all_boiler", "all_boilerplate"),
                             ("any_visible", "any_visible"),
                             ("any_polygon", "any_polygon")):
                if wa[src] is not None:
                    r[dst] = wa[src]
            if wa["best_len"] is not None:
                r["best_description_len"] = wa["best_len"]
        out.append((
            r["cluster_id"], r["n_sites"], cls,
            int(all_blacklisted), int(cls in CLASS_SOFT_BLACKLIST),
            r["has_name"], r["gtc"], r["any_polygon"], r["area"],
            r["dim_len"], r["dim_h"], r["dim_area"],
            r["best_description_len"], r["all_boilerplate"],
            r["any_measurements"], r["any_visible"],
            r["sitelinks"], r["has_image"], r["has_commons"],
            dw, db, da, dr, dbl, nb,
            now if not args.skip_spatial else None, now,
        ))
        if i and i % 20000 == 0:
            print(f"  {i:,}/{len(rows):,}  {i/(time.time()-t0):.0f}/s")

    conn.executescript(SCHEMA)
    with conn:
        conn.executemany(
            f"INSERT INTO signals VALUES ({','.join('?'*27)})", out)
    conn.executescript(INDEXES)
    conn.commit()
    print(f"Wrote {len(out):,} signal rows in {time.time()-t0:.0f}s")
    conn.close()


if __name__ == "__main__":
    main()
