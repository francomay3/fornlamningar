"""Stars for the exported set, after the top-N cut has already been made.

Membership of the export is still `score_full`: the best 6,000 in the
country. This file does not reopen that cut. It only decides, inside it,
what the app shows as stars and which pin wins a spot when the map thins.

Five stars is readership. Sixty-five places in the export have 3,000 or
more Wikipedia reads in a trailing year, and those are the ones a person
already knows by name. Four stars is the rest of that fame — 500 reads is
enough to have been sought out — or, with no such article, a high score
from the comparisons. One, two and three are that same score, cut where
the mass of it actually sits. Stretching it onto 0..100 and slicing every
25 points puts two thirds of the export on one star and seventeen places
on four, because one church ruin sets the top of the scale.

The weights are the logistic fit to the comparisons as of 2026-10-01
(157 decisive votes, L2 12), divided back out of the standardized
differences so a place is scored on its own features. `fornvard` and
`is_church` are in it because those two, and not the rest of the class
list, are what the votes followed. A later batch of votes does not move
this until the weights are refit on purpose: the map is a build, not a
live model.
"""

import math
import os
import sqlite3

import paths
from export_compare_pool import _far, _log1p, _near

# On the linear score below. A place at or above a cut gets that many
# stars, unless readership already gave it more.
MODEL_CUTS = (
    (1.6, 4),
    (0.8, 3),
    (0.3, 2),
)
VIEWS_FIVE = 3000
VIEWS_FOUR = 500

# coef = fitted_weight / sd(feature difference). Order is the contract
# with features() below.
COEF = (
    0.33190706,   # has_name
    0.16737199,   # any_visible
    -0.01482883,  # has_image
    0.12151480,   # has_commons
    -0.10095829,  # has_wl_image
    0.14819577,   # n_images
    0.06309382,   # log_len
    0.01000578,   # log_height
    0.01640558,   # log_area
    -0.03192870,  # log_desc
    0.19417651,   # far_building
    0.13513906,   # far_road
    0.85749190,   # near_monument
    -0.01604450,  # near_viewpoint
    -0.32353775,  # docs
    0.05192136,   # sitelinks
    1.50805203,   # fornvard
    1.43439081,   # is_church
)


def stars_for(views, interest):
    """1..5. Readership outranks the model, and never the other way."""
    views = views or 0
    got = 1
    for cut, stars in MODEL_CUTS:
        if interest >= cut:
            got = stars
            break
    if views >= VIEWS_FIVE:
        return 5
    if views >= VIEWS_FOUR:
        return max(4, got)
    return got


def rank_key(row):
    """Best first.

    Stars decide the band. Inside five stars, and inside the four-star
    places that earned it by being read, more reads win: that is the order
    the map should reveal while zooming out. Everywhere else the comparison
    score breaks the tie. cluster_id keeps a re-run from shuffling equals.
    """
    views = row["views"] or 0
    read = views if views >= VIEWS_FOUR else -1
    return (-row["stars"], -read, -row["interest"], row["cluster_id"])


def _chunks(items, size=400):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fornvard_uuids():
    """Every register uuid a county lists as a monument it maintains.

    Matched on any member of the cluster, not only the representative.
    The county names whichever record it surveyed; the pin is the cluster.
    """
    if not os.path.exists(paths.LANSSTYRELSEN):
        print("  ! lansstyrelsen.sqlite missing; fornvard is 0 everywhere")
        return set()
    db = sqlite3.connect(f"file:{paths.LANSSTYRELSEN}?mode=ro", uri=True)
    return {u for (u,) in db.execute(
        "SELECT m.uuid FROM matches m "
        "JOIN datasets d ON d.id = m.dataset_id "
        "WHERE d.kind = 'fornvard'")}


def _image_counts(uuids):
    if not uuids or not os.path.exists(paths.PLACES):
        if not os.path.exists(paths.PLACES):
            print("  ! places.sqlite missing; photo counts are 0")
        return {}
    db = sqlite3.connect(f"file:{paths.PLACES}?mode=ro", uri=True)
    out = {}
    ids = [u for u in uuids if u]
    for chunk in _chunks(ids):
        marks = ",".join("?" * len(chunk))
        for uuid, n in db.execute(
                f"SELECT uuid, COUNT(*) FROM images "
                f"WHERE uuid IN ({marks}) GROUP BY uuid", chunk):
            out[uuid] = n
    return out


def _members(work, cluster_ids):
    out = {}
    for chunk in _chunks(cluster_ids):
        marks = ",".join("?" * len(chunk))
        for cid, uuid in work.execute(
                f"SELECT cluster_id, uuid FROM site_clusters "
                f"WHERE cluster_id IN ({marks})", chunk):
            out.setdefault(cid, []).append(uuid)
    return out


def _signals(work, cluster_ids):
    cols = (
        "wiki_views_12m", "has_name", "any_visible", "has_image",
        "has_commons", "has_wl_image", "dim_len_m", "dim_height_m",
        "env_area_m2", "best_description_len", "dist_to_building_m",
        "dist_to_road_m", "dist_to_osm_monument_m", "dist_to_osm_viewpoint_m",
        "doc_sources_n", "sitelinks",
    )
    out = {}
    for chunk in _chunks(cluster_ids):
        marks = ",".join("?" * len(chunk))
        for row in work.execute(
                f"SELECT cluster_id, {', '.join(cols)} FROM signals "
                f"WHERE cluster_id IN ({marks})", chunk):
            out[row[0]] = row[1:]
    return out


def features(sig, n_images, fornvard, is_church):
    """One row of the linear score. Missing distances count as far, the
    same way the comparison pool encodes them."""
    if sig is None:
        sig = (None,) * 16
    (views, has_name, visible, image, commons, wl,
     length, height, area, desc,
     building, road, monument, viewpoint, docs, sitelinks) = sig
    return (
        float(has_name or 0),
        float(visible or 0),
        float(image or 0),
        float(commons or 0),
        float(wl or 0),
        _log1p(n_images),
        _log1p(length),
        _log1p(height),
        _log1p(area),
        _log1p(desc),
        _far(building, 200),
        _far(road, 200),
        _near(monument, 200),
        _near(viewpoint, 500),
        _log1p(docs),
        _log1p(sitelinks),
        1.0 if fornvard else 0.0,
        1.0 if is_church else 0.0,
    ), (views or 0)


def interest_of(feats):
    return sum(c * x for c, x in zip(COEF, feats))


def rank_cut(rows, db=None):
    """Attach views, interest and stars, and return the rows best-first.

    `rows` is the export after the score_full cut. Each item is a dict
    with cluster_id, uuid and dominant_class.
    """
    db = db or paths.WORK
    work = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ids = [r["cluster_id"] for r in rows]
    signals = _signals(work, ids)
    members = _members(work, ids)
    maintained = _fornvard_uuids()
    images = _image_counts([r["uuid"] for r in rows])

    for r in rows:
        sig = signals.get(r["cluster_id"])
        uuids = members.get(r["cluster_id"], ())
        feats, views = features(
            sig,
            images.get(r["uuid"], 0),
            any(u in maintained for u in uuids),
            (r["dominant_class"] or "") == "Kyrka/kapell",
        )
        r["views"] = views
        r["interest"] = interest_of(feats)
        r["stars"] = stars_for(views, r["interest"])
    rows.sort(key=rank_key)
    return rows


def summarize(rows):
    hist = {}
    for r in rows:
        hist[r["stars"]] = hist.get(r["stars"], 0) + 1
    return hist


if __name__ == "__main__":
    work = sqlite3.connect(f"file:{paths.WORK}?mode=ro", uri=True)
    work.row_factory = sqlite3.Row
    raw = work.execute("""
        SELECT c.cluster_id, c.name, c.dominant_class, c.rep_uuid AS uuid
          FROM clusters c
          JOIN scores sc ON sc.cluster_id = c.cluster_id
         WHERE c.lon IS NOT NULL
           AND sc.excluded_hard = 0 AND sc.excluded_soft = 0
         ORDER BY sc.score_full DESC
         LIMIT 6000
    """).fetchall()
    ranked = rank_cut([dict(r) for r in raw])
    hist = summarize(ranked)
    print("stars: " + "  ".join(f"{s}*:{hist.get(s, 0):,}" for s in (5, 4, 3, 2, 1)))
    print("first 12:")
    for r in ranked[:12]:
        print(f"  {r['stars']}*  views={r['views']:<7}  {r['interest']:5.2f}  {r['name']}")
    # The readership rules are exact. A miss here is a bug, not a judgment.
    five = [r for r in ranked if r["stars"] == 5]
    assert all(r["views"] >= VIEWS_FIVE for r in five), "a five below 3000 reads"
    assert all(r["stars"] >= 4 for r in ranked if r["views"] >= VIEWS_FOUR)
    assert not any(r["stars"] == 5 and r["views"] < VIEWS_FIVE for r in ranked)
    print(f"checks ok ({len(five)} fives, all at >= {VIEWS_FIVE} reads)")
