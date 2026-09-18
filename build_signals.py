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

Reads:  src/data/work.sqlite            (sites, clusters, site_clusters, wikidata)
        src/data/osm/sweden_ways.gpkg    (highway lines, SWEREF99)
        src/data/osm/boards.gpkg         (tourism=information nodes, SWEREF99)
Writes: src/data/work.sqlite            (table `signals`)

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

from families import CLASS_BLACKLIST, CLASS_SOFT_BLACKLIST

import paths

DB = paths.WORK
WAYS_GPKG = "src/data/osm/sweden_ways.gpkg"
BOARDS_GPKG = "src/data/osm/boards.gpkg"
ARCH_GPKG = "src/data/osm/historic_pt.gpkg"
ARCH_POLY_GPKG = "src/data/osm/historic_poly.gpkg"
BUILDINGS_GPKG = "src/data/osm/buildings.gpkg"
PARKING_GPKG = "src/data/osm/parking_pt.gpkg"
PARKING_POLY_GPKG = "src/data/osm/parking_poly.gpkg"
# RAA's own record of where archaeology has been dug. Two files: the areas an
# assignment covered, and the trenches actually opened inside them.
DIG_GPKG = ("src/data/raa/arkeologiska_uppdrag_undersökningsområden_"
            "sverige.gpkg")
WIKIMEDIA_DB = paths.WIKIMEDIA

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



def load_poly_centroids(path, layer, where=""):
    """Envelope centres of a polygon layer.

    A centre is not a polygon, and for a big area that matters -- but every
    consumer here is a nearest-distance query where the alternative is
    densifying 279,426 car parks, and a car park is small enough that its
    centre is within metres of its edge. The excavation areas are the case
    to watch: the biggest are hundreds of metres across, so `dug_here` uses
    the bounding box rather than this.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out = []
    q = f'SELECT geom FROM "{layer}" WHERE geom IS NOT NULL {where}'
    for (blob,) in conn.execute(q):
        e = gpkg_envelope(blob) if blob and len(blob) >= 40 else None
        if e:
            out.append(((e[0] + e[1]) / 2, (e[2] + e[3]) / 2))
    conn.close()
    return np.array(out) if out else np.zeros((0, 2))


def load_dig_boxes(path):
    """(emin, emax, nmin, nmax) for every investigated area.

    Kept as boxes, not centres, because `dug_here` asks whether this place
    falls INSIDE one and these polygons are large enough for the difference
    to decide the answer.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    layers = [r[0] for r in conn.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'")]
    boxes = []
    for lyr in layers:
        if not lyr.endswith("polygon"):
            continue
        for (blob,) in conn.execute(f'SELECT geom FROM "{lyr}" '
                                    "WHERE geom IS NOT NULL"):
            e = gpkg_envelope(blob) if blob and len(blob) >= 40 else None
            if e:
                boxes.append(e)
    conn.close()
    return boxes


def wiki_views(work_db, wm_db):
    """cluster_id -> total trailing-12-month readership, sv + en.

    Summed across languages and MAXed across the cluster's member sites: a
    cluster is one place, and the readership of the place is the readership
    of the article about it, wherever that article sits.
    """
    if not os.path.exists(wm_db):
        return {}
    wm = sqlite3.connect(f"file:{wm_db}?mode=ro", uri=True)
    per_uuid = {}
    for uuid, v in wm.execute("SELECT uuid, SUM(COALESCE(views_12m, 0)) "
                              "FROM wiki_articles GROUP BY uuid"):
        per_uuid[uuid] = v
    w = sqlite3.connect(f"file:{work_db}?mode=ro", uri=True)
    out = {}
    for uuid, cid in w.execute("SELECT uuid, cluster_id FROM site_clusters"):
        v = per_uuid.get(uuid)
        if v is not None:
            out[cid] = max(out.get(cid, 0), v)
    return out


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
    -- Somewhere to leave the car. Franco asked whether this is worth having
    -- and the measurement below is the answer; the point of adding it is to
    -- be able to say no with a number. Trafikverket's Rastplatser were tried
    -- first and are the wrong dataset -- motorway service areas, nowhere
    -- near a grave field. A car park at one of these places is a gravel
    -- pull-in at the end of a forest track, which is what OSM has.
    dist_to_parking_m REAL,
    -- Distance to the nearest area RAA has archaeologically investigated,
    -- and whether one covers this place.
    --
    -- READ THIS BEFORE TRUSTING IT. Excavation in Sweden is overwhelmingly
    -- development-driven: someone digs because a road or a housing estate is
    -- going in, not because the monument is remarkable. So a dig nearby is
    -- evidence of CONSTRUCTION, and only indirectly of interest. It is in
    -- here to be measured, not because the causal story is clean.
    dist_to_dig_m REAL,
    dug_here INTEGER,
    -- Wikipedia readership over the trailing twelve months, summed across
    -- sv and en. NULL means no article; 0 means an article nobody reads,
    -- which is a different and useful fact. Only refines the ~12% of places
    -- that have an article at all -- having views requires having a page.
    wiki_views_12m INTEGER,
    neighbors_1km INTEGER,
    spatial_checked_at TEXT,
    wikidata_checked_at TEXT,
    -- Evidence from people, not from documents. See visitor_signals().
    visitors_n INTEGER,
    visitor_text INTEGER,
    -- Count of DOCUMENTARY source kinds, from places.sqlite. See
    -- doc_source_counts(); consumed only by score_full.
    doc_sources_n INTEGER
);
"""
INDEXES = """
CREATE INDEX idx_sig_class ON signals(dominant_class);
CREATE INDEX idx_sig_way   ON signals(dist_to_way_m);
CREATE INDEX idx_sig_board ON signals(dist_to_board_m);
CREATE INDEX idx_sig_name  ON signals(has_name);
CREATE INDEX idx_sig_views ON signals(wiki_views_12m DESC);
"""


# Source kinds that are somebody having WRITTEN about a place. `register` is
# excluded because every cluster has one by definition, so counting it would
# produce a constant. `user_comment` is excluded for the opposite reason: it is
# not documentation, and it is counted separately as visitor_text.
DOC_KINDS = ("wikipedia", "county_page", "county_pdf", "county_plan",
             "county_programme", "county_attr", "tradition",
             "register_parts", "sign_ocr")


def visitor_signals(conn):
    """Who has actually been there, from the app's contribution log.

    WHY THIS IS A SIGNAL AND NOT A LABEL, which is the whole point of it.
    Until now a visit entered through build_labels.py as a training label, so
    it taught the model what visit-worthiness correlates with GLOBALLY and did
    nothing at all to the score of the place visited. Franco's own note in
    build_labels.py had already identified why that matters -- "a person
    standing at the place and answering is a different kind of evidence, and
    it is the kind this fit has never had" -- and then the evidence was spent
    on the weights instead of on the place.

    It also belongs in score_intrinsic, unlike everything else that credits a
    place for being known. The argument in build_scores.LABEL_DERIVED is that
    Wikipedia and OSM presence "reflects OSM mappers and Wikipedia editors
    documenting the same famous places, which is the same circularity as the
    labels themselves". A visitor is not an editor: the observation is
    independent of the documentation the labels are drawn from, so it is the
    one confirmation that can raise a score without closing the loop.

    DISTINCT AUTHORS, not events. One person tapping "been here" on three
    phones is one person, and the count exists so that "two independent people
    found this" can be a stronger feature than one.

    `been` FALSE IS NOT COUNTED. It is the opposite claim -- somebody stood
    within fifty metres and saw nothing -- and it stays where it is, as a
    verified negative label.
    """
    if not os.path.exists(paths.CONTRIBUTIONS):
        return {}, {}
    # The app's place id is the representative site's uuid, so it has to come
    # back through site_clusters to be a cluster. A uuid with no cluster is a
    # place this pipeline has never seen and is skipped, not invented.
    cl = dict(conn.execute("SELECT uuid, cluster_id FROM site_clusters"))
    src = sqlite3.connect(paths.ro(paths.CONTRIBUTIONS), uri=True)
    seen, texts = {}, {}
    for uuid, author, kind, payload in src.execute(
            "SELECT place_uuid, author, kind, payload FROM events "
            "WHERE kind IN ('presence', 'visit', 'comment')"):
        cid = cl.get(uuid)
        if cid is None:
            continue
        try:
            d = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if kind == "comment":
            if (d.get("body") or "").strip():
                texts[cid] = 1
        elif kind == "visit" or d.get("been") is True:
            seen.setdefault(cid, set()).add(author)
    src.close()
    return {k: len(v) for k, v in seen.items()}, texts


def doc_source_counts():
    """How many INDEPENDENT documentary kinds mention each cluster.

    Read from places.sqlite, which means build_sources.py has to run before
    this stage -- it used to run after, which is why "a source mentions this
    place" could not be a feature at all no matter how obviously it should be.

    Kinds and not rows. Four paragraphs of the same county PDF is one source
    having an opinion; a Wikipedia article AND a county plan AND a recorded
    tradition is three. Counting rows would let one verbose document outweigh
    three independent ones.

    Returns empty when places.sqlite is absent, which is not an error: the
    feature simply carries no information on that run, and build_scores reads
    the column as 0.
    """
    if not os.path.exists(paths.PLACES):
        return {}
    src = sqlite3.connect(paths.ro(paths.PLACES), uri=True)
    try:
        q = ",".join("?" * len(DOC_KINDS))
        return dict(src.execute(
            f"SELECT cluster_id, COUNT(DISTINCT kind) FROM sources "
            f"WHERE usable = 1 AND text <> '' AND kind IN ({q}) "
            f"GROUP BY cluster_id", DOC_KINDS))
    finally:
        src.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB)
    p.add_argument("--ways", default=WAYS_GPKG)
    p.add_argument("--boards", default=BOARDS_GPKG)
    p.add_argument("--arch", default=ARCH_GPKG)
    p.add_argument("--arch-poly", default=ARCH_POLY_GPKG)
    p.add_argument("--buildings", default=BUILDINGS_GPKG)
    p.add_argument("--parking", default=PARKING_GPKG)
    p.add_argument("--parking-poly", default=PARKING_POLY_GPKG)
    p.add_argument("--digs", default=DIG_GPKG)
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
    print(f"  {len(worthy_agg):,} clusters with at least one non-blacklisted member")

    way_grid = board_grid = arch_grid = road_grid = bldg_grid = None
    park_grid = dig_grid = None
    dig_boxes = []
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
        pk = []
        if os.path.exists(args.parking):
            pk.extend(load_points(args.parking, "park").tolist())
        if os.path.exists(args.parking_poly):
            pk.extend(load_poly_centroids(args.parking_poly, "park").tolist())
        if pk:
            pa = np.array(pk)
            print(f"  {len(pa):,} car parks")
            park_grid = PointGrid(pa[:, 0], pa[:, 1])
            del pa, pk
        else:
            print(f"  ! {args.parking} missing; dist_to_parking_m will be NULL")
        if os.path.exists(args.digs):
            dig_boxes = load_dig_boxes(args.digs)
            print(f"  {len(dig_boxes):,} investigated areas")
            if dig_boxes:
                dc = np.array([((b[0] + b[1]) / 2, (b[2] + b[3]) / 2)
                               for b in dig_boxes])
                dig_grid = PointGrid(dc[:, 0], dc[:, 1])
                del dc
        else:
            print(f"  ! {args.digs} missing; dist_to_dig_m will be NULL")
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

    views = wiki_views(args.db, WIKIMEDIA_DB)
    if views:
        nz = sum(1 for v in views.values() if v)
        print(f"  {len(views):,} places have a Wikipedia article "
              f"({nz:,} with any readership)")

    visitors, texts = visitor_signals(conn)
    if visitors or texts:
        repeat = sum(1 for v in visitors.values() if v > 1)
        print(f"  {len(visitors):,} places confirmed by a visitor "
              f"({repeat:,} by more than one), {len(texts):,} with visitor text")
    docs = doc_source_counts()
    if docs:
        multi = sum(1 for v in docs.values() if v > 1)
        print(f"  {len(docs):,} places mentioned by a documentary source "
              f"({multi:,} by two or more kinds)")
    else:
        print("  ! no places.sqlite -- doc_sources_n is 0 for every cluster, "
              "so score_full loses that feature this run")

    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = []
    t0 = time.time()
    for i, r in enumerate(rows):
        e, n = r["centroid_e"], r["centroid_n"]
        dw = db = da = dr = dbl = None
        dpk = ddig = None
        dug = 0
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
            if park_grid:
                dpk = park_grid.nearest(e, n, max_search=5000.0)
            if dig_grid:
                ddig = dig_grid.nearest(e, n, max_search=5000.0)
                # Containment is checked against the bounding boxes only when
                # the centre is close enough for it to be possible, which
                # keeps a 74,000-box scan off the hot path for the 95% of
                # places that were never dug near.
                if ddig is not None and ddig <= 2000.0:
                    for b in dig_boxes:
                        if b[0] <= e <= b[1] and b[2] <= n <= b[3]:
                            dug = 1
                            break
            k = dens_grid._range(int(e // 1000.0) * 100_000 + int(n // 1000.0))
            nb = int(k[1] - k[0]) if k else 0
        # THE CLASS IS READ, NOT CHOSEN. This used to pick the cluster's most
        # SIGNIFICANT class -- `max` over its members by measured positive
        # rate -- while build_clusters.py picked its representative with
        # families.representative_order and build_tiles.py drew that one's
        # icon. Two rules about the same question, and they disagreed for
        # 6,015 clusters, 751 of them among the 10,000 that ship.
        #
        # It was not a tie, it was a bias. `max` picks the cluster's most
        # FLATTERING member, so a Fardvag holding one runestone scored as a
        # runestone: over those 751 the score's class carried a higher weight
        # in 725 of them, mean +1.50 on a scale capped at +/-2.0. The pin
        # showed a route, the text described a route, and it ranked as rock
        # art. A score is a prediction about what the visitor finds AT THIS
        # PIN, so it has to be about the same stone the pin, the icon and the
        # description are about.
        #
        # representative_order keeps the fix this code was written for --
        # Blomsholms gravfalt, 240 m and ~40 monuments, called "Omrade med
        # fossil akermark" because it shared an RAA number with two
        # fossil-field records -- because its first clause is that a
        # blacklisted class loses. Measured: exactly 1 cluster of 251,029
        # wears a blacklisted class while holding a clean member.
        member = members.get(r["cluster_id"], set())
        worthy = member - CLASS_BLACKLIST
        cls = r["dominant_class"]
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
            dw, db, da, dr, dbl, dpk, ddig, dug, views.get(r["cluster_id"]),
            nb,
            now if not args.skip_spatial else None, now,
            visitors.get(r["cluster_id"], 0),
            texts.get(r["cluster_id"], 0),
            docs.get(r["cluster_id"], 0),
        ))
        if i and i % 20000 == 0:
            print(f"  {i:,}/{len(rows):,}  {i/(time.time()-t0):.0f}/s")

    conn.executescript(SCHEMA)
    with conn:
        conn.executemany(
            f"INSERT INTO signals VALUES ({','.join('?'*34)})", out)
    conn.executescript(INDEXES)
    conn.commit()
    print(f"Wrote {len(out):,} signal rows in {time.time()-t0:.0f}s")
    conn.close()


if __name__ == "__main__":
    main()
