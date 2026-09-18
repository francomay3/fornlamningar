#!/usr/bin/env python3
"""
Stage 6: score and rank clusters.

Two scores, deliberately separate, because "can I get there and find it?" and
"is it worth the trip?" need different evidence:

    accessibility_score  -- way proximity, board proximity, visibility
    notability_score     -- folk name, description substance, class, geometry

Weights are log-lifts measured against the label set (naive-Bayes style), so
every weight is traceable to an observed enrichment rather than guessed. They
are computed at runtime on a TRAIN half of the labels and evaluated on the
held-out half, so the reported quality is not self-congratulatory.

Two scores are emitted per cluster:

    score_intrinsic -- uses NO label-derived feature. This is the one that can
                       honestly be validated against the labels.
    score_full      -- additionally credits Wikipedia sitelinks, a Wikidata
                       photograph and a Commons category. Better for production
                       ranking (an article really is evidence), but it CANNOT be
                       validated against labels drawn from those same fields --
                       that would be circular.

Filters are applied as flags, never as deletions, so thresholds stay tunable.

Reads / writes: src/data/work.sqlite  (table `scores`)

Usage:
    python build_scores.py
    python build_scores.py --top 40
"""

import argparse
import math
import random
import sqlite3
import sys

# The blacklists reach this stage as COLUMNS (`class_blacklisted`,
# `class_soft_blacklisted`) computed by build_signals. CLASS_BURIED is read
# here directly instead, and that is deliberate rather than inconsistent:
# families.py exists precisely so that more than one stage can read the
# taxonomy, its rule needs no new column -- `any_visible` is already in
# signals -- and applying it here means adding a class to it does not require
# re-running stage 4.
from families import CLASS_BURIED, CLASS_NOT_A_PLACE

import numpy as np

import logistic as LR

import paths

DB = paths.WORK

# Each entry: name -> predicate over the signals row.
# Label-derived features are kept in a separate dict to prevent leakage.
# Cap on any single access weight. The board signal measures 10.20x lift, but
# hand-verified ground truth shows it is NOT detecting heritage signage: four
# sites confirmed on the ground to have signs have their nearest OSM board
# 1,134-3,029 m away, in a municipality with 6x the national board density
# (4.10 vs 0.69 per 100 km2). OSM `tourism=information` nodes sit at trailheads
# and town centres, not at fornlamningar. The lift is real but it is proxying
# "in a visited area", so an uncapped +2.32 would let a confounder dominate --
# and absence of a board carries almost no information at all.
ACCESS_WEIGHT_CAP = 1.2

ACCESS_FEATURES = {
    "way_le_25":     lambda r: r["dist_to_way_m"] is not None and r["dist_to_way_m"] <= 25,
    "way_le_100":    lambda r: r["dist_to_way_m"] is not None and r["dist_to_way_m"] <= 100,
    "way_remote":    lambda r: r["dist_to_way_m"] is None or r["dist_to_way_m"] > 500,
    "board_le_200":  lambda r: r["dist_to_board_m"] is not None and r["dist_to_board_m"] <= 200,
    "board_le_1km":  lambda r: r["dist_to_board_m"] is not None and r["dist_to_board_m"] <= 1000,
    "visible":       lambda r: bool(r["any_visible"]),
}

SIZE_FEATURES = {
    # Physical size, parsed from the Swedish description. `dim_h_gt_2` is the
    # strongest single feature measured anywhere in this project (11.89x,
    # sigma +62.7): two metres of height is visible from a distance, which is
    # what "monumental" actually means.
    "dim_h_gt_1":     lambda r: (r["dim_height_m"] or 0) > 1,
    "dim_h_gt_2":     lambda r: (r["dim_height_m"] or 0) > 2,
    "dim_len_gt_10":  lambda r: (r["dim_len_m"] or 0) > 10,
    "dim_area_gt_100": lambda r: (r["dim_area_m2"] or 0) > 100,
    "no_dims":        lambda r: r["dim_height_m"] is None and r["dim_len_m"] is None,
}

ACCESS2_FEATURES = {
    # Drivable-road proximity answers "can I park near it", which is a different
    # question from dist_to_way_m (any path).
    "road_le_50":   lambda r: r["dist_to_road_m"] is not None and r["dist_to_road_m"] <= 50,
    "road_le_200":  lambda r: r["dist_to_road_m"] is not None and r["dist_to_road_m"] <= 200,
    "road_gt_1km":  lambda r: r["dist_to_road_m"] is None or r["dist_to_road_m"] > 1000,
    # Counter-intuitive but measured: proximity to buildings is POSITIVE (2.87x)
    # and remoteness NEGATIVE (0.55x). The allemansratten reasoning -- near a
    # house means a private garden -- is true for individual cases but wrong at
    # population level: remote sites are the charcoal pits and hunting traps.
    "bldg_lt_60":   lambda r: r["dist_to_building_m"] is not None and r["dist_to_building_m"] < 60,
    "bldg_gt_200":  lambda r: r["dist_to_building_m"] is None or r["dist_to_building_m"] > 200,
}

# The candidates added to answer a specific question: the score gets
# AUC 0.90 against Wikidata positives and 0.60 against county
# recommendations, and the gap is not a shortage of labels -- the county
# labels were already in the fit when that was measured. So either the
# features do not carry the signal, or we were missing features. These are
# the cheapest ways to find out, kept in their own dict so they can be
# switched off with --without and the difference read directly. The verdict
# is in CANDIDATE_GROUPS below: both groups help, neither closes the gap.
CANDIDATE_GROUPS = {
    "parking": ("park_le_100", "park_le_500", "park_remote", "log_park"),
    "digs": ("dug_here", "dig_le_500", "log_dig"),
    # dug_here on its own, because it looked like the one to throw away and
    # was not. Measured, each row being that group REMOVED:
    #
    #   removed             AUC      county-noWD   prec@100   rec@500
    #   both candidates    0.8054      0.7243        51 %     168/2342
    #   digs               0.8086      0.7269        56 %     190/2342
    #   parking            0.8073      0.7278        56 %     180/2342
    #   dug_here only      0.8089      0.7274        57 %     190/2342
    #   nothing            0.8100      0.7297        60 %     191/2342
    #
    # So everything stays. Two things worth keeping straight:
    #
    # Parking and digs are near-additive, so they are not measuring the same
    # fact -- and on the county metric, the one that actually means "worth the
    # trip", digs alone edge out parking alone.
    #
    # dug_here has 1.17x lift and a decorrelated weight of -0.171, which
    # reads like two reasons to drop it and is one fact seen twice. A
    # NEGATIVE weight is still information: once log_road and log_way are
    # accounted for, sitting inside an investigated area marks
    # development-driven excavation, so the feature earns its place by
    # pushing DOWN places that look reachable but are merely next to
    # roadworks. Removing it costs 3 points of precision@100.
    #
    # It is still a bounding-box test over 31% of the country, so if it ever
    # needs to carry more weight than this, do the point-in-polygon properly
    # first.
    "dug_here": ("dug_here",),
}

CANDIDATE_FEATURES = {
    # Somewhere to leave the car, from OSM rather than from Trafikverket's
    # motorway rest areas.
    "park_le_100":  lambda r: (r["dist_to_parking_m"] is not None
                               and r["dist_to_parking_m"] <= 100),
    "park_le_500":  lambda r: (r["dist_to_parking_m"] is not None
                               and r["dist_to_parking_m"] <= 500),
    "park_remote":  lambda r: (r["dist_to_parking_m"] is None
                               or r["dist_to_parking_m"] > 2000),
    # Somebody has dug here. Read the schema comment in build_signals before
    # believing this means the place is interesting: excavation in Sweden is
    # development-driven, so it is mostly evidence that a road was built.
    "dug_here":     lambda r: bool(r["dug_here"]),
    "dig_le_500":   lambda r: (r["dist_to_dig_m"] is not None
                               and r["dist_to_dig_m"] <= 500),
}

# Somebody has been there and said so.
#
# IN score_intrinsic, deliberately, and it is the only "this place is known"
# evidence that belongs there. The exclusion argued for in LABEL_DERIVED below
# rests on circularity -- Wikipedia and OSM credit the same famous places the
# labels are drawn from -- and a visitor is not an editor. The observation is
# independent of the documentation, so it can raise a place's score without
# teaching the model to rank documentation.
#
# It is also the first feature here that MOVES A SPECIFIC PLACE for a reason
# that came from a person. Everything else is measured off the register and
# OSM; this is the only input a user can change by going somewhere.
#
# Two thresholds because agreement is worth more than a single report, and
# because the weights are measured: if the second visitor adds nothing, the
# fit will say so rather than us assuming it.
VISITOR_FEATURES = {
    "visited":         lambda r: (r["visitors_n"] or 0) > 0,
    "visited_2plus":   lambda r: (r["visitors_n"] or 0) > 1,
    # Someone wrote something about it standing there, which is a stronger
    # claim than having ticked a box.
    "visitor_text":    lambda r: bool(r["visitor_text"]),
}

NOTABILITY_FEATURES = {
    "has_name":        lambda r: bool(r["has_name"]),
    "desc_gt_300":     lambda r: (r["best_description_len"] or 0) > 300,
    "all_boilerplate": lambda r: bool(r["all_boilerplate"]),
    "multi_site":      lambda r: (r["n_sites"] or 1) > 1,
    "multi_geometry":  lambda r: (r["geom_type_count"] or 0) > 1,
    "blacklisted":     lambda r: bool(r["class_blacklisted"]),
    "soft_blacklist":  lambda r: bool(r["class_soft_blacklisted"]),
}

# Evidence that IS the label source. Usable for ranking, unusable for validation.
# "Somebody already documented this" evidence. Deliberately confined to
# score_full. These have huge measured lift (OSM archaeological_site: 24.3x)
# but they CANNOT help discovery: every one of six hand-verified sites has its
# nearest OSM archaeological_site 1,230-7,371 m away. High lift here reflects
# OSM mappers and Wikipedia editors documenting the same famous places, which is
# the same circularity as the labels themselves. Keeping them out of
# score_intrinsic is what lets that score find undocumented sites.
# Wikipedia readership belongs HERE and not among the candidates, and it took
# writing it in the wrong place to see why: having views requires having an
# article, so `views > 0` is `has_sitelinks` with extra resolution. It can
# rank the documented 12% more finely. It cannot find anything undocumented,
# which is the whole job of score_intrinsic.
LABEL_DERIVED = {
    "views_gt_100":     lambda r: (r["wiki_views_12m"] or 0) > 100,
    "views_gt_1000":    lambda r: (r["wiki_views_12m"] or 0) > 1000,
    "has_sitelinks":    lambda r: (r["sitelinks"] or 0) > 0,
    "has_image":        lambda r: bool(r["has_image"]),
    "has_commons":      lambda r: bool(r["has_commons"]),
    "osm_arch_le_100":  lambda r: (r["dist_to_osm_arch_m"] is not None
                                   and r["dist_to_osm_arch_m"] <= 100),
    # "A source mentions this place", which could not be a feature at all
    # until build_sources.py was moved ahead of build_signals.py: the corpus
    # was built after the scoring that wanted to read it.
    #
    # HERE and not in the intrinsic set, for the reason this whole dict
    # exists. A county plan or a Wikipedia article is somebody having written
    # about a place, so crediting it ranks the documented above the
    # undocumented -- which is true, useful, and exactly the circularity
    # score_intrinsic exists to avoid. Both scores are emitted; which one
    # ships is a product decision, not this file's.
    "doc_2plus":        lambda r: (r["doc_sources_n"] or 0) > 1,
    "doc_3plus":        lambda r: (r["doc_sources_n"] or 0) > 2,
}

# Per-class weight smoothing. A class with few clusters cannot support a strong
# weight, so its rate is shrunk toward the global base rate by PSEUDO_COUNT
# pseudo-observations. Prevents a 3-cluster class from scoring +3.
PSEUDO_COUNT = 60.0
CLASS_WEIGHT_CAP = 2.0

# --------------------------------------------------------------------------- #
# Judgement tiers over the measured class weights.
#
# The labels measure DOCUMENTATION, not visit-worthiness, so classes that are
# well recorded and roadside score well even when nobody would drive to them --
# `Hyttomrade`, `Dammvall`, `Granmarke`, `Lagenhetsbebyggelse` all surfaced in
# the top undocumented results. These offsets encode "would a person travel to
# see this?", which is a judgement the data cannot supply.
#
# Offsets are deliberately small relative to the measured weights (+/-2.0 cap):
# they nudge the ranking, they do not override the evidence.
TIER_A = 0.6    # a destination in its own right
TIER_C = -0.9   # real, legible, usually roadside -- but not a trip
CLASS_TIER = {
    # Tier A: monumental, visually striking, or unique
    "Stenkammargrav": TIER_A, "Gånggrift": TIER_A, "Dös": TIER_A,
    "Hällkista": TIER_A, "Gravfält": TIER_A, "Hög": TIER_A,
    "Röse": TIER_A, "Skeppssättning": TIER_A, "Stenkrets/stenrad": TIER_A,
    "Hällristning": TIER_A, "Runristning": TIER_A, "Bildristning": TIER_A,
    "Hällmålning": TIER_A, "Borg": TIER_A, "Fornborg": TIER_A,
    "Ruin": TIER_A, "Kyrka/kapell": TIER_A, "Kloster": TIER_A,
    "Labyrint": TIER_A, "Domarring": TIER_A, "Treudd": TIER_A,
    "Begravningsplats": TIER_A, "Minnesmärke": TIER_A,
    "Grav markerad av sten/block": TIER_A, "Stenkistgrav": TIER_A,
    "Offerkast": TIER_A, "Källa med tradition": TIER_A,

    # Tier C: industrial, infrastructural or administrative. Well described and
    # easy to reach, which is exactly why the labels overrate them.
    "Hyttområde": TIER_C, "Hammarområde": TIER_C, "Dammvall": TIER_C,
    "Gränsmärke": TIER_C, "Vägmärke": TIER_C, "Lägenhetsbebyggelse": TIER_C,
    "Kalkugn": TIER_C, "Kvarn": TIER_C, "Bro": TIER_C, "Vägbank": TIER_C,
    "Husgrund, historisk tid": TIER_C,
    "Småindustriområde": TIER_C, "Kemisk industri": TIER_C,
    "Blästbrukslämning": TIER_C, "Blästplats": TIER_C, "Tomtning": TIER_C,
    "Vattenverk": TIER_C, "Sågverk": TIER_C, "Tegelbruk": TIER_C,
    "Gruvhål": TIER_C, "Stenbrott": TIER_C, "Täktområde": TIER_C,
    "Område med skogsbrukslämningar": TIER_C, "Kåta": TIER_C,
    "Färdväg": TIER_C, "Bytomt/gårdstomt": TIER_C,
}

# RAA's class taxonomy is too coarse for ranking: `Stenkrets/stenrad` lumps 241
# skeppssattningar (2.9% labelled) in with 1,678 domarringar (0.89%), and
# `Stenkammargrav` covers both plain cists and gaanggrifter. The description text
# names the actual monument form, and it is a far stronger signal than the class:
# `gaanggrift` measures 34.6x (sigma +41.6) against 2.0 for the whole class.
#
# Note the spelling variants -- "skeppssattning" and "skeppsattning" both occur,
# and matching only one loses 69 of 241 sites.
DESC_KEYWORDS = {
    "kyrkoruin":      ("yrkoruin", "losterruin"),
    "ganggrift":      ("ånggrift",),
    "hallmalning":    ("ällmålning",),
    "dos":            ("dös", "Dös"),
    "hallkista":      ("ällkista",),
    "skeppssattning": ("keppssättning", "keppsättning"),
    "rest_sten":      ("est sten",),
    "domarring":      ("omarring",),
}
KEYWORD_MIN_SIGMA = 3.0


def keyword_weights(rows, positives, desc):
    """Smoothed log-lift per description keyword, keeping only significant ones.

    Only keywords reaching KEYWORD_MIN_SIGMA are retained, so a term that merely
    looks meaningful cannot earn a weight.
    """
    from collections import Counter
    tot = len(rows)
    npos = sum(positives.get(r["cluster_id"], 0.0) for r in rows)
    base = npos / tot if tot else 0.0
    out = {}
    for name, pats in DESC_KEYWORDS.items():
        n = 0
        k = 0.0
        for r in rows:
            d = desc.get(r["cluster_id"]) or ""
            if any(p in d for p in pats):
                n += 1
                k += positives.get(r["cluster_id"], 0.0)
        if n < 20 or not base:
            continue
        pb = n / tot
        sd = math.sqrt(npos * pb * (1 - pb)) or 1.0
        sigma = (k - npos * pb) / sd
        if sigma < KEYWORD_MIN_SIGMA:
            continue
        rate = (k + PSEUDO_COUNT * base) / (n + PSEUDO_COUNT)
        out[name] = (max(-CLASS_WEIGHT_CAP,
                         min(CLASS_WEIGHT_CAP, math.log(max(rate, 1e-6) / base))),
                     pats, n, sigma)
    return out


def keyword_bonus(cluster_id, desc, kw):
    """Largest matching keyword weight. MAX, not sum: `dos` and `ganggrift` are
    both megalithic and would double-count."""
    d = desc.get(cluster_id) or ""
    best = 0.0
    for name, (w, pats, _n, _s) in kw.items():
        if any(p in d for p in pats):
            best = max(best, w)
    return best


def class_weights(rows, positives):
    """Smoothed log-lift per dominant_class.

    Class is the single best a-priori statement about whether a monument type is
    worth travelling to -- a gaanggrift is worth a detour, a charcoal pit is not
    -- and using it only as a blacklist flag threw that away. Megalithic tombs
    with no folk name and no mapped signpost were scoring mid-pack as a result.
    """
    from collections import Counter
    n_c, k_c = Counter(), Counter()
    for r in rows:
        c = r["dominant_class"] or "?"
        n_c[c] += 1
        k_c[c] += positives.get(r["cluster_id"], 0.0)
    tot = len(rows)
    npos = sum(positives.get(r["cluster_id"], 0.0) for r in rows)
    base = npos / tot if tot else 0.0
    out = {}
    for c, n in n_c.items():
        rate = (k_c[c] + PSEUDO_COUNT * base) / (n + PSEUDO_COUNT)
        w = math.log(max(rate, 1e-6) / base) if base else 0.0
        w += CLASS_TIER.get(c, 0.0)          # judgement nudge, applied pre-cap
        out[c] = max(-CLASS_WEIGHT_CAP, min(CLASS_WEIGHT_CAP, w))
    return out


# Signals measured and deliberately DROPPED:
#   neighbors_1km  -- 0.94x lift, sigma -0.7. No signal. Spatial density of
#                     other remains says nothing about whether a place is worth
#                     visiting, contrary to expectation.
#   env_area_m2    -- ~1.2x lift. Having a polygon matters slightly; its size
#                     does not.


def measure_weights(rows, features, positives):
    """log-lift per feature, computed on the given positives.

    `positives` maps cluster_id -> weight, so a hand label marked "just an
    impression" (certainty 1, weight 0.33) counts for a third of a label the
    reviewer stood in front of. Automatic labels carry weight 1.0.
    """
    tot = len(rows)
    npos = sum(positives.get(r["cluster_id"], 0.0) for r in rows)
    weights, stats = {}, {}
    for name, f in features.items():
        kb = sum(1 for r in rows if f(r))
        kp = sum(positives.get(r["cluster_id"], 0.0) for r in rows if f(r))
        if kb == 0 or npos == 0:
            weights[name] = 0.0
            continue
        pb, pp = kb / tot, (kp / npos if npos else 0.0)
        lift = (pp / pb) if pb else 0.0
        weights[name] = math.log(max(lift, 0.02))
        sd = math.sqrt(npos * pb * (1 - pb)) or 1.0
        stats[name] = (lift, (kp - npos * pb) / sd)
    return weights, stats


def score_of(r, features, weights):
    return sum(w for name, w in weights.items()
               if name in features and features[name](r))


def auc(scored):
    """Rank-based AUC. scored = [(score, label), ...]"""
    s = sorted(scored, key=lambda x: x[0])
    pos = sum(1 for _, l in s if l)
    neg = len(s) - pos
    if not pos or not neg:
        return float("nan")
    rank_sum, i = 0.0, 0
    while i < len(s):
        j = i
        while j < len(s) and s[j][0] == s[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2.0          # 1-based average rank for ties
        rank_sum += sum(avg_rank for k in range(i, j) if s[k][1])
        i = j
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


CONTINUOUS = [
    ("log_dim_h",   lambda r: math.log1p(r["dim_height_m"] or 0)),
    ("log_dim_len", lambda r: math.log1p(r["dim_len_m"] or 0)),
    ("log_desc",    lambda r: math.log1p(r["best_description_len"] or 0)),
    ("log_way",     lambda r: math.log1p(r["dist_to_way_m"] if r["dist_to_way_m"] is not None else 5000)),
    ("log_road",    lambda r: math.log1p(r["dist_to_road_m"] if r["dist_to_road_m"] is not None else 5000)),
    ("log_bldg",    lambda r: math.log1p(r["dist_to_building_m"] if r["dist_to_building_m"] is not None else 2000)),
    ("log_board",   lambda r: math.log1p(r["dist_to_board_m"] if r["dist_to_board_m"] is not None else 5000)),
    ("log_nsites",  lambda r: math.log1p(r["n_sites"] or 1)),
]

# Continuous forms of the candidates, separated so --no-candidates removes the
# boolean buckets and these together. Leaving them in CONTINUOUS would have
# made the ablation measure nothing while appearing to work.
CONTINUOUS_CANDIDATE = [
    ("log_park",    lambda r: math.log1p(r["dist_to_parking_m"] if r["dist_to_parking_m"] is not None else 5000)),
    ("log_dig",     lambda r: math.log1p(r["dist_to_dig_m"] if r["dist_to_dig_m"] is not None else 5000)),
]


def build_matrix(rows, feats, cw, kw, desc, cont=None):
    """Feature matrix for logistic regression: booleans + continuous + scalars."""
    cont = CONTINUOUS if cont is None else cont
    names = list(feats) + [n for n, _ in cont] + ["class_w", "keyword_w"]
    X = np.zeros((len(rows), len(names)))
    for i, r in enumerate(rows):
        j = 0
        for _n, f in feats.items():
            X[i, j] = 1.0 if f(r) else 0.0
            j += 1
        for _n, f in cont:
            X[i, j] = f(r)
            j += 1
        X[i, j] = cw.get(r["dominant_class"] or "?", 0.0); j += 1
        X[i, j] = keyword_bonus(r["cluster_id"], desc, kw)
    return X, names


def fit_logistic(rows, feats, cw, kw, desc, positives, negatives, train_pos,
                 seed=1, neg_sample=40000, cont=None):
    """Fit on positives (weighted) vs verified negatives + sampled unlabelled.

    Most unlabelled clusters really are negative (base rate ~0.75%), so
    sampling them as negatives is the standard positive-unlabelled approach and
    is far more informative than 10 verified negatives on their own.
    """
    rng = np.random.default_rng(seed)
    pos_rows = [r for r in rows if r["cluster_id"] in train_pos]
    neg_rows = [r for r in rows if r["cluster_id"] in negatives]
    unl = [r for r in rows
           if r["cluster_id"] not in positives and r["cluster_id"] not in negatives]
    idx = rng.choice(len(unl), size=min(neg_sample, len(unl)), replace=False)
    sampled = [unl[i] for i in idx]

    train_rows = pos_rows + neg_rows + sampled
    y = np.r_[np.ones(len(pos_rows)),
              np.zeros(len(neg_rows) + len(sampled))]
    # Verified negatives are worth more than sampled unlabelled ones, which are
    # only PROBABLY negative.
    sw = np.r_[[train_pos[r["cluster_id"]] for r in pos_rows],
               np.full(len(neg_rows), 3.0),
               np.ones(len(sampled))]
    X, names = build_matrix(train_rows, feats, cw, kw, desc, cont)
    Xs, mu, sd = LR.standardise(X)
    w, b = LR.fit(Xs, y, sample_weight=sw, l2=5.0, iters=4000)
    return w, b, mu, sd, names


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--without", action="append", default=[],
                   choices=sorted(CANDIDATE_GROUPS) + ["candidates"],
                   help="fit without a candidate group, to measure what it "
                        "is worth. Repeatable.")
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM signals").fetchall()
    desc = {cid: d for cid, d in conn.execute(
        "SELECT cluster_id, best_description FROM clusters")}
    # cluster_id -> label weight. MAX across member sites, so one confidently
    # labelled site is enough to mark the cluster.
    # Clamped to 1.0: `weight` is confidence in the label, so no single label
    # may ever count as more than one observation.
    # Contribution = interest x confidence. A modest site seen clearly counts
    # 0.5; a great site barely glimpsed counts 0.33. Clamped to 1.0 so no single
    # label can ever outweigh one observation.
    pos_all = {r[0]: min(1.0, r[1]) for r in conn.execute(
        "SELECT sc.cluster_id, MAX(l.label * COALESCE(l.weight, 1.0)) "
        "FROM labels l JOIN site_clusters sc ON sc.uuid = l.uuid "
        "WHERE l.label > 0 GROUP BY sc.cluster_id")}
    # Where each positive came from, kept per cluster and written out with the
    # score.
    #
    # The shipped score (score_intrinsic) uses no label-derived feature, so
    # this is not an input to it -- the labels only shape the fitted weights,
    # globally. It matters for the other direction: when a user eventually says
    # "this does not deserve five stars", the first question is whether the
    # label behind it was Franco's own judgement or a Wikidata proxy. Today
    # that is 23 hand labels against 4,369 proxies, and without this column
    # there is no way to tell them apart after the fact.
    pos_src = {r[0]: r[1] for r in conn.execute(
        "SELECT sc.cluster_id, GROUP_CONCAT(DISTINCT l.source) "
        "FROM labels l JOIN site_clusters sc ON sc.uuid = l.uuid "
        "WHERE l.label > 0 GROUP BY sc.cluster_id")}

    # Verified negatives DO feed the fit -- see fit_logistic below. The log-lift
    # baseline still cannot use them (it compares positives against the base
    # rate over all 245k clusters, which has no slot for a known negative), and
    # this note used to say they were unused for exactly that reason. That
    # stopped being true when the logistic fit became the only shipped model,
    # and the message stayed behind: it was telling us a gap existed that had
    # already been closed.
    neg_all = {r[0] for r in conn.execute(
        "SELECT DISTINCT sc.cluster_id FROM labels l "
        "JOIN site_clusters sc ON sc.uuid = l.uuid WHERE l.label = 0")}
    if neg_all:
        print(f"  {len(neg_all):,} verified negatives, used by the logistic fit "
              f"(the lift baseline cannot use them)")

    # Runestones are 83% of the label set; keeping them makes every weight a
    # runestone detector. Fit on everything else.
    fit_rows = [r for r in rows if r["dominant_class"] != "Runristning"]
    fit_pos = {r["cluster_id"]: pos_all[r["cluster_id"]]
               for r in fit_rows if r["cluster_id"] in pos_all}
    print(f"clusters {len(rows):,}   fitting on {len(fit_rows):,} "
          f"non-runestone ({len(fit_pos):,} positives)")

    rng = random.Random(args.seed)
    shuffled = sorted(fit_pos)
    rng.shuffle(shuffled)
    half = len(shuffled) // 2
    train = {k: fit_pos[k] for k in shuffled[:half]}
    test = set(shuffled[half:])
    print(f"  train positives {len(train):,}   test positives {len(test):,}\n")

    feats = {**ACCESS_FEATURES, **ACCESS2_FEATURES,
             **SIZE_FEATURES, **NOTABILITY_FEATURES, **VISITOR_FEATURES}
    drop = set()
    for g in args.without:
        if g == "candidates":
            for names in CANDIDATE_GROUPS.values():
                drop.update(names)
        else:
            drop.update(CANDIDATE_GROUPS[g])
    feats.update({k: v for k, v in CANDIDATE_FEATURES.items()
                  if k not in drop})
    cont = list(CONTINUOUS) + [(n, f) for n, f in CONTINUOUS_CANDIDATE
                               if n not in drop]
    if drop:
        print(f"  (excluded: {', '.join(sorted(drop))})")
    weights, stats = measure_weights(fit_rows, feats, train)
    for name in {**ACCESS_FEATURES, **ACCESS2_FEATURES}:
        if name in weights:
            weights[name] = max(-ACCESS_WEIGHT_CAP,
                                min(ACCESS_WEIGHT_CAP, weights[name]))
    print(f"{'feature':<20}{'lift':>8}{'weight':>9}{'sigma':>8}")
    print("-" * 45)
    for name in feats:
        lift, sig = stats.get(name, (float('nan'), float('nan')))
        print(f"{name:<20}{lift:>7.2f}x{weights[name]:>+9.2f}{sig:>+8.1f}")

    lw, _ = measure_weights(fit_rows, LABEL_DERIVED, train)
    # Class and keyword weights are fitted on ALL rows, runestones included.
    # Excluding runestones is there to stop them dominating the FEATURE weights
    # (has_name, dimensions, ...), since 83% of the label set is runic. It must
    # not extend to class weights: dropping them left `Runristning` absent from
    # the table entirely, i.e. weight 0, so only 8% of Sweden's runestones --
    # among the most visitable archaeology it has -- reached the top 10,000,
    # while Stenkammargrav, Borg and Fornborg all sat at +2.0.
    train_all = {r["cluster_id"]: pos_all[r["cluster_id"]]
                 for r in rows if r["cluster_id"] in train
                 or (r["dominant_class"] == "Runristning"
                     and r["cluster_id"] in pos_all)}
    cw = class_weights(rows, train_all)
    kw = keyword_weights(rows, train_all, desc)
    print("\ndescription-keyword weights (significant only, sigma >= 3)")
    for name, (w, _p, n, sg) in sorted(kw.items(), key=lambda x: -x[1][0]):
        print(f"  {name:<16}{w:+.2f}   n={n:>6,}  sigma {sg:+.1f}")
    top = sorted(cw.items(), key=lambda x: -x[1])
    print("\nper-class weights (smoothed log-lift, capped +/-2.0)")
    print("  strongest:", ", ".join(f"{c}={w:+.2f}" for c, w in top[:6]))
    print("  weakest:  ", ", ".join(f"{c}={w:+.2f}" for c, w in top[-6:]))

    # --- fit the logistic model too, so the two can be compared ------------ #
    neg_all = neg_all if 'neg_all' in dir() else set()
    # The model is no longer selectable, and that is the point. Log-lift used
    # to be an option AND the default, which cost us: run_pipeline.sh does not
    # pass --model, so a full rebuild silently refitted with the worse model.
    # The score range moved from 9.92..1.03 to 16.08..5.40 and nothing looked
    # broken -- the ranking was just quietly worse.
    #
    # Lift double-counts correlated features. Near a road, near a building and
    # photographed on Wikidata are largely one fact -- that a place is known
    # and reachable -- and lift rewards it three times.
    #
    # The lift score is still COMPUTED, as the baseline the logistic fit is
    # measured against below. It is simply no longer shippable.
    print("\nfitting logistic regression...")
    lr_model = fit_logistic(fit_rows, feats, cw, kw, desc,
                            pos_all, neg_all, train, seed=args.seed,
                            cont=cont)
    w_lr, b_lr, mu, sd, names = lr_model
    top = sorted(zip(names, w_lr), key=lambda x: -abs(x[1]))[:12]
    print("  pesos mas fuertes (decorrelacionados):")
    for n_, v in top:
        print(f"    {n_:<18}{v:+.3f}")

    # score_full: ONE fit over every feature, not the intrinsic fit plus a
    # sum of log-lifts on top.
    #
    # The comment above says lift double-counts correlated features and that
    # it is therefore no longer shippable. That reasoning was applied to
    # score_intrinsic and then not to score_full, which kept being computed as
    # `intrinsic + score_of(LABEL_DERIVED, lw)` -- a naive-Bayes sum over six
    # features that are largely one latent variable. Measured over all 251,029
    # clusters on 2026-09-18: has_sitelinks correlates 0.79 with has_commons,
    # 0.72 with has_image and 0.66 with views_gt_100, and views_gt_100/1000 are
    # nested inside has_sitelinks by construction. Adding their lifts credits
    # "this place is documented" about four times.
    #
    # THE ANSWER IS NOT TO DROP THEM. Franco's point, and he is right: these
    # are good predictors and non-independence is a thing to MODEL, not a
    # reason to throw information away. A logistic fit is exactly the estimator
    # that handles it -- with L2 it partials out the shared variance and gives
    # each feature its marginal contribution given the others, so a block of
    # five near-copies gets one block's worth of weight instead of five.
    #
    # And the correlation matrix says not all of them are the same block:
    # osm_arch_le_100 correlates only 0.10 with has_sitelinks, so OSM mappers
    # and Wikipedia editors are largely marking DIFFERENT places. That is real
    # independent evidence, and the old formula was drowning it in four copies
    # of Wikipedia.
    #
    # What this does NOT fix is leakage: the positives are largely
    # Wikidata-derived, so any model holding has_sitelinks will predict them
    # well without having learned anything about visit-worthiness. That is why
    # the per-source AUCs below matter more than the headline one, and why the
    # two to read are the label sets NOT drawn from these fields -- "county,
    # excluding wikidata" and "hand".
    feats_full = {**feats, **LABEL_DERIVED}
    print("\nfitting logistic regression (score_full, with documentation)...")
    lr_full = fit_logistic(fit_rows, feats_full, cw, kw, desc,
                           pos_all, neg_all, train, seed=args.seed, cont=cont)
    w_full, b_full, mu_full, sd_full, names_full = lr_full
    doc_w = sorted(((n, v) for n, v in zip(names_full, w_full)
                    if n in LABEL_DERIVED), key=lambda x: -abs(x[1]))
    print("  documentation weights, marginal (compare with the lifts above):")
    for n_, v in doc_w:
        print(f"    {n_:<18}{v:+.3f}   (lift weight was {lw.get(n_, 0.0):+.2f})")

    def full_score(r):
        return (score_of(r, feats, weights)
                + cw.get(r["dominant_class"] or "?", 0.0)
                + keyword_bonus(r["cluster_id"], desc, kw))

    # --- evaluate the honest score on held-out positives ------------------- #
    eval_rows = [r for r in fit_rows
                 if r["cluster_id"] not in train]          # drop train leakage
    Xe, _ = build_matrix(eval_rows, feats, cw, kw, desc, cont)
    pe = LR.predict((Xe - mu) / sd, w_lr, b_lr)
    scored = [(float(pe[i]), int(r["cluster_id"] in test))
              for i, r in enumerate(eval_rows)]
    a_lift = auc([(full_score(r), int(r["cluster_id"] in test))
                  for r in eval_rows])
    print(f"\n  comparacion en held-out:  lift AUC {a_lift:.4f}   "
          f"logistic AUC {auc(scored):.4f}   (lift = baseline, not shipped)")
    a = auc(scored)
    scored.sort(key=lambda x: -x[0])
    n_test = sum(l for _, l in scored)
    print(f"\nheld-out validation (score_intrinsic, no label-derived features)")
    print(f"  AUC {a:.4f}   test positives {n_test:,} of {len(scored):,} clusters")
    for k in (100, 500, 1000, 5000):
        hits = sum(l for _, l in scored[:k])
        print(f"  recall@{k:<5} {hits:>4}/{n_test}  ({100*hits/max(n_test,1):>5.1f}%)"
              f"   precision {100*hits/k:>5.2f}%   lift "
              f"{(hits/k)/(n_test/len(scored)):>5.1f}x")

    # --- the same score against each definition of "good" ------------------ #
    #
    # One AUC over a mixed label set hides the only number that matters. The
    # Wikidata positives and the county recommendations disagree about what is
    # worth visiting, and the score is much better at agreeing with Wikidata
    # -- which is unsurprising, because Wikidata positives are places somebody
    # already wrote about, and most of our features measure exactly that.
    # A county board recommending a place it maintains is a judgement about
    # whether it is worth the trip, which is the question we actually mean.
    # Reported separately so the shipped number cannot flatter itself.
    by_src = {}
    for cid in test:
        for src in (pos_src.get(cid) or "?").split(","):
            by_src.setdefault(src.strip(), set()).add(cid)
    # The two Wikidata routes are one source of truth wearing two names:
    # `wikidata_image` and `wikidata_sitelinks` both mean "somebody has
    # already published about this". Grouped, because the interesting
    # comparison is against the county boards, and leaving them apart made
    # the set subtracted below empty -- the first version of this block
    # looked up a source called "wikidata", which does not exist, and so
    # silently reported the county AUC twice.
    wd = set()
    for k, v in by_src.items():
        if k.startswith("wikidata"):
            wd |= v
    if wd:
        by_src["wikidata (both routes)"] = wd
    print("\n  the same model, scored against each definition of good:")
    rows_by_cid = {r["cluster_id"]: i for i, r in enumerate(eval_rows)}
    def auc_for(subset, label):
        if len(subset) < 20:
            return
        sc = [(float(pe[i]), int(r["cluster_id"] in subset))
              for i, r in enumerate(eval_rows)]
        # A label source drawn from the SAME places a feature marks cannot
        # validate that feature, and the number it produces is not a weak
        # result -- it is a meaningless one that looks like an excellent one.
        # Measured on 2026-09-18, the first run with VISITOR_FEATURES: the
        # contribution labels scored AUC 0.9993, because every place Franco
        # rated is a place he had also confirmed a visit to, so `visited` and
        # `visitor_text` hand the model the answer. Said out loud here rather
        # than left for somebody to celebrate.
        echo = " <- reads its own feature, not a validation" if (
            label.startswith("user:")) else ""
        print(f"    {label:<34} n={len(subset):>5}   AUC {auc(sc):.4f}{echo}")
    for src, subset in sorted(by_src.items(), key=lambda x: -len(x[1])):
        auc_for(subset, src)
    auc_for(by_src.get("county", set()) - wd, "county, excluding wikidata")
    auc_for(by_src.get("hand", set()) - wd, "hand, excluding wikidata")

    # The same table for score_full, which is the only way to answer "does
    # crediting documentation actually help?" honestly.
    #
    # Read the LAST TWO ROWS and not the first. A label set drawn from
    # Wikidata cannot say whether has_sitelinks is a good feature -- it is the
    # label wearing a different hat, and the number will be near 1 whatever
    # the model does. "county, excluding wikidata" and "hand" are the two
    # sources with no overlap with these fields, so they are the two that can
    # tell an improvement from an echo.
    Xef, _ = build_matrix(eval_rows, feats_full, cw, kw, desc, cont)
    pef = LR.predict((Xef - mu_full) / sd_full, w_full, b_full)
    print("\n  score_full, the same definitions (read the last two):")

    def auc_full(subset, label):
        if len(subset) < 20:
            return
        sc = [(float(pef[i]), int(r["cluster_id"] in subset))
              for i, r in enumerate(eval_rows)]
        base = [(float(pe[i]), int(r["cluster_id"] in subset))
                for i, r in enumerate(eval_rows)]
        a_f, a_i = auc(sc), auc(base)
        print(f"    {label:<34} n={len(subset):>5}   AUC {a_f:.4f}   "
              f"intrinsic {a_i:.4f}   {a_f - a_i:+.4f}")

    auc_full(test, "held-out positives (all sources)")
    for src, subset in sorted(by_src.items(), key=lambda x: -len(x[1])):
        auc_full(subset, src)
    auc_full(by_src.get("county", set()) - wd, "county, excluding wikidata")
    auc_full(by_src.get("hand", set()) - wd, "hand, excluding wikidata")

    # --- write scores ------------------------------------------------------ #
    conn.execute("DROP TABLE IF EXISTS scores")
    conn.execute("""
        CREATE TABLE scores (
            cluster_id TEXT PRIMARY KEY,
            class_weight REAL,
            keyword_weight REAL,
            accessibility_score REAL,
            notability_score REAL,
            score_intrinsic REAL,
            score_full REAL,
            excluded_hard INTEGER,
            excluded_soft INTEGER,
            -- Comma-joined `labels.source` values for this cluster's positive
            -- labels; NULL for the ~99% with no label at all.
            label_sources TEXT
        )
    """)
    # Clusters a county board recommends, which rescue an excluded class.
    county_pos = {r[0] for r in conn.execute(
        "SELECT sc.cluster_id FROM labels l "
        "JOIN site_clusters sc ON sc.uuid = l.uuid "
        "WHERE l.source = 'county' AND l.label > 0")}
    if county_pos:
        print(f"  {len(county_pos):,} clusters recommended by a county board "
              f"(rescues an excluded class)")

    # Clusters the REGISTER has struck out, which are excluded outright.
    #
    # This is a veto, and the long comment below argues against vetoes. It is
    # not a contradiction, because it is not the same kind of judgement. That
    # argument is about TASTE: a class prior saying "a fossil field is dull on
    # average" must not outrank a county board saying "go and see this one",
    # and a veto by construction never learns it was wrong because the sites
    # it hides never come back to argue. Here the register is not saying a
    # place is dull. It is saying the RECORD IS NOT A PLACE.
    #
    #   Utgar pa grund av felregistrering -- struck out as a mis-registration
    #   Overford till annan lamning       -- merged into another record
    #
    # The first never existed; the second still exists, at another id, and
    # keeping this one puts two pins on one monument. No amount of site-level
    # evidence makes either into somewhere to visit, so none of the rescue
    # conditions apply: a mis-registration with a Wikidata sitelink is still a
    # mis-registration.
    #
    # ONLY WHEN EVERY MEMBER SITE IS STRUCK OUT. The 274 struck sites fall in
    # 230 clusters, but 25 of those also contain live sites -- a gravfalt where
    # one of a hundred graves was a duplicate entry is still a gravfalt, and
    # excluding it over one bad row would be a far worse error than the one
    # being fixed. That leaves 205, of which 76 currently survive the other
    # filters and reach the app.
    struck = {r[0] for r in conn.execute("""
        SELECT sc.cluster_id FROM site_clusters sc
        JOIN sites s ON s.uuid = sc.uuid
        GROUP BY sc.cluster_id
        HAVING sum(CASE WHEN s.aktualitetsstatus IN
                        ('Utgår på grund av felregistrering',
                         'Överförd till annan lämning')
                   THEN 1 ELSE 0 END) = count(*)
    """)}
    if struck:
        print(f"  {len(struck):,} clusters struck out by the register "
              f"(mis-registered or merged; excluded outright)")

    Xa, _ = build_matrix(rows, feats, cw, kw, desc, cont)
    lr_all = LR.predict((Xa - mu) / sd, w_lr, b_lr)
    Xaf, _ = build_matrix(rows, feats_full, cw, kw, desc, cont)
    lr_full_all = LR.predict((Xaf - mu_full) / sd_full, w_full, b_full)

    out = []
    for i, r in enumerate(rows):
        acc = (score_of(r, ACCESS_FEATURES, weights)
               + score_of(r, ACCESS2_FEATURES, weights))
        kb = keyword_bonus(r["cluster_id"], desc, kw)
        nob = (score_of(r, NOTABILITY_FEATURES, weights)
               + score_of(r, SIZE_FEATURES, weights)
               + cw.get(r["dominant_class"] or "?", 0.0) + kb)
        # x10 only to put the probability on a readable 0-10 scale. Nothing
        # downstream depends on the magnitude, only on the ordering.
        intrinsic = float(lr_all[i]) * 10.0
        full = float(lr_full_all[i]) * 10.0
        # ONE exclusion rule now, not two.
        #
        # The hard blacklist used to be an unconditional veto on 16 classes
        # and the soft one an exclusion that any independent positive evidence
        # could overturn. They are the same rule at different strengths, so
        # they are now the same rule: excluded by class, rescued by evidence
        # about THIS site.
        #
        # What changed my mind is that the veto was contradicted by an
        # authority. Lansstyrelsen i Hallands lan publishes L1996:2248 and
        # L1998:9620 ("Omrade med fossil akermark") and L1996:4046 ("Fossil
        # aker") as places to go and see -- three classes the blacklist
        # removed that morning. The class-level judgement is still right on
        # average: a random fossil field is an invisible scatter of clearance
        # cairns. But a class prior cannot outrank site-level evidence, and a
        # veto by construction never learns that it was wrong, because the
        # sites it hides never come back to argue.
        #
        # The prior is not lost. `class_w` -- the smoothed positive rate per
        # class -- is the model's STRONGEST feature at +1.431, so these
        # classes are still pushed down hard; they are pushed down by measured
        # evidence rather than by a list, and a site with a county board
        # behind it can climb back out.
        #
        # A county recommendation is a rescue condition for exactly that
        # reason: it is the only one of these that is a human saying "go
        # here", rather than a proxy for the place being well documented.
        #
        # IT HAS TO BE A PAGE ABOUT THIS PLACE, NOT A PAGE NEARBY. There used
        # to be a second form of this condition -- `dist_to_board_m <= 500` --
        # and it was rescuing 2,845 clusters of excluded classes, almost as
        # many as the 2,895 that had real evidence. 1,193 Stensättning and 841
        # Boplats were in the export because a county board recommended
        # something ELSE within 500 m.
        #
        # What it was actually measuring is urbanity. 45% of Stadslager sit
        # within 500 m of a recommendation against 5.4% of all clusters, an
        # eightfold rate, because a stadslager IS a town centre and a town
        # centre is where the boards put their signs. Boplats, equally
        # invisible but rural, sits at the 5.0% baseline.
        #
        # And the decisive argument is internal: build_clusters groups by RAA
        # GROUP and not by proximity, because "grouping by proximity is us
        # guessing" -- its spatial pass was removed after measuring that it
        # chained 535 sites over six kilometres into one place. Mean cluster
        # spread is 45 m. So two clusters 300 m apart are two monuments THE
        # COUNTY ITSELF filed separately, and a page about one is evidence
        # about one. This condition was that rejected guess, reintroduced at
        # the scoring stage at ten times the radius the clustering refused.
        #
        # The exact form loses almost nothing: of the 8,294 clusters within
        # 500 m of a recommendation, only 288 also had a page of their own --
        # so the radius contributed 8,006 cases where the board was talking
        # about something else. Shrinking it was the alternative and it is
        # worse than removing it: at 50 m it still rescues 76 clusters, and
        # those are precisely the ones the county distinguished from their
        # neighbour, so the rescue would be contradicting the judgement it
        # exists to defer to. No radius is defensible, so there is no radius.
        rescued = (bool(r["has_name"]) or (r["sitelinks"] or 0) > 0
                   or bool(r["has_image"])
                   or r["cluster_id"] in county_pos)
        # A CLASS WHERE THE ORDINARY RESCUES MEASURE THE WRONG THING gets its
        # own, narrower one: see CLASS_BURIED in families.py. For a stadslager
        # `has_name` is the name of the TOWN on top of it, so it carries no
        # information about whether there is anything to see; the register's
        # own "visible above ground" does. This overrides `rescued` rather
        # than adding to it -- the point is that the others do not count.
        if (r["dominant_class"] or "") in CLASS_BURIED:
            rescued = bool(r["any_visible"])
        # `or in struck` and not `and not rescued`: see the note where
        # `struck` is built. A record the register has withdrawn is not a
        # place with a bad prior, it is not a place.
        # CLASS_NOT_A_PLACE sits beside `struck` and not beside the
        # blacklist, for the same reason: it is not a place with a bad prior,
        # it is not a place. No rescue, because both conditions that could
        # rescue one of these describe something else -- see families.py.
        hard = int((bool(r["class_blacklisted"]) and not rescued)
                   or ((r["dominant_class"] or "") in CLASS_BURIED
                       and not rescued)
                   or (r["dominant_class"] or "") in CLASS_NOT_A_PLACE
                   or r["cluster_id"] in struck)
        soft = int(bool(r["class_soft_blacklisted"]) and not rescued)
        out.append((r["cluster_id"], cw.get(r["dominant_class"] or "?", 0.0),
                    kb, acc, nob, intrinsic, full, hard, soft,
                    pos_src.get(r["cluster_id"])))
    with conn:
        conn.executemany(
            "INSERT INTO scores VALUES (?,?,?,?,?,?,?,?,?,?)", out)
    conn.executescript("""
        CREATE INDEX idx_sc_full ON scores(score_full DESC);
        CREATE INDEX idx_sc_intr ON scores(score_intrinsic DESC);
        CREATE INDEX idx_sc_excl ON scores(excluded_hard, excluded_soft);
    """)
    conn.commit()

    kept = conn.execute("SELECT COUNT(*) FROM scores "
                        "WHERE excluded_hard=0 AND excluded_soft=0").fetchone()[0]
    print(f"\nwrote {len(out):,} scores; {kept:,} survive the filters "
          f"({100*kept/len(out):.1f}%)")
    conn.close()


if __name__ == "__main__":
    main()
