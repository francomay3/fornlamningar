#!/usr/bin/env python3
"""The pool the admin tinder compares, one JSON line per place.

The 6,000 that ship, minus anything with 500 or more Wikipedia reads in a
year. Those already have their order: five stars from 3,000 reads, four
from 500. This file is everyone else. The score is stored so a pair can
be described, and the signals are the ones the comparisons actually
followed: a name, photographs, standing away from buildings. Not "Franco
went there", and not the readership the cut just used.

    franco-may/data/compare-pool.jsonl.gz

The admin refits a pairwise model from votes on top of this file. Voting
does not regenerate it. A places build does, because that is when the
score and the signals it was cut from are current.
"""

import gzip
import json
import math
import os
import sqlite3

import paths

# Names and order are the contract with franco-may/lib/compare-model.ts.
# Visitors and readership stay out: a visit is the old score's label, and
# readership is how the top of the export is already ordered. What remains
# is what lined up with Franco's comparisons — a name, a visible monument,
# photographs, and whether it stands away from buildings and roads.
FEATURES = (
    "has_name",
    "any_visible",
    "has_image",
    "has_commons",
    "has_wl_image",
    "n_images",
    "log_len",
    "log_height",
    "log_area",
    "log_desc",
    "far_building",
    "far_road",
    "near_monument",
    "near_viewpoint",
    "docs",
    "sitelinks",
)

# Below the four-star line. Sites at or above it are ordered by readership
# and are not asked.
VIEWS_BELOW = 500
EXPORT_N = 6000


def _log1p(value):
    return round(math.log1p(max(0.0, value or 0.0)), 4)


def _near(value, scale):
    """1 next to the thing, 0 when it is far or was never measured."""
    if value is None:
        return 0.0
    value = float(value)
    if value < 0:
        return 0.0
    return round(1.0 / (1.0 + value / scale), 4)


def _far(value, scale):
    return round(1.0 - _near(value, scale), 4)


def write_compare_pool(path=None):
    path = path or os.path.join(paths.WEB, "data", "compare-pool.jsonl.gz")
    work = sqlite3.connect(f"file:{paths.WORK}?mode=ro", uri=True)
    places = sqlite3.connect(f"file:{paths.PLACES}?mode=ro", uri=True)
    titles = dict(places.execute(
        "SELECT uuid, title FROM features WHERE uuid IS NOT NULL AND title IS NOT NULL"))
    images = dict(places.execute(
        "SELECT uuid, COUNT(*) FROM images WHERE uuid IS NOT NULL GROUP BY uuid"))
    rows = work.execute(f"""
        SELECT c.rep_uuid, c.name, sig.dominant_class, c.lat, c.lon,
               sc.score_full, sig.wiki_views_12m,
               COALESCE(sig.has_name, 0),
               COALESCE(sig.any_visible, 0),
               COALESCE(sig.has_image, 0),
               COALESCE(sig.has_commons, 0),
               COALESCE(sig.has_wl_image, 0),
               COALESCE(sig.dim_len_m, 0),
               COALESCE(sig.dim_height_m, 0),
               COALESCE(sig.env_area_m2, 0),
               COALESCE(sig.best_description_len, 0),
               sig.dist_to_building_m,
               sig.dist_to_road_m,
               sig.dist_to_osm_monument_m,
               sig.dist_to_osm_viewpoint_m,
               COALESCE(sig.doc_sources_n, 0),
               COALESCE(sig.sitelinks, 0)
          FROM clusters c
          JOIN scores sc ON sc.cluster_id = c.cluster_id
          JOIN signals sig ON sig.cluster_id = c.cluster_id
         WHERE c.lon IS NOT NULL
           AND sc.excluded_hard = 0 AND sc.excluded_soft = 0
           AND c.rep_uuid IS NOT NULL AND c.rep_uuid <> ''
         ORDER BY sc.score_full DESC
         LIMIT {EXPORT_N}
    """).fetchall()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"v": 2, "features": list(FEATURES)},
                            ensure_ascii=False) + "\n")
        for (uuid, register_name, kind, lat, lon, score, views,
             has_name, visible, image, commons, wl,
             length, height, area, desc,
             building, road, monument, viewpoint, docs, sitelinks) in rows:
            if views is not None and views >= VIEWS_BELOW:
                continue
            title = (titles.get(uuid) or register_name or "").strip()
            feats = [
                int(has_name), int(visible), int(image), int(commons), int(wl),
                _log1p(images.get(uuid, 0)),
                _log1p(length), _log1p(height), _log1p(area), _log1p(desc),
                _far(building, 200), _far(road, 200),
                _near(monument, 200), _near(viewpoint, 500),
                _log1p(docs), _log1p(sitelinks),
            ]
            fh.write(json.dumps({
                "id": uuid,
                "name": title,
                "kind": kind or "",
                "lat": lat,
                "lon": lon,
                "score": round(score, 4),
                "views": views,
                "f": feats,
            }, ensure_ascii=False) + "\n")
            n += 1
    print(f"compare:  {n:,} below {VIEWS_BELOW} reads -> {path}")
    return n


if __name__ == "__main__":
    write_compare_pool()
