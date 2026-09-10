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

Reads / writes: src/data/sites.sqlite  (table `scores`)

Usage:
    python build_scores.py
    python build_scores.py --top 40
"""

import argparse
import math
import random
import sqlite3
import sys

import numpy as np

import logistic as LR

DB = "src/data/sites.sqlite"

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
LABEL_DERIVED = {
    "has_sitelinks":    lambda r: (r["sitelinks"] or 0) > 0,
    "has_image":        lambda r: bool(r["has_image"]),
    "has_commons":      lambda r: bool(r["has_commons"]),
    "osm_arch_le_100":  lambda r: (r["dist_to_osm_arch_m"] is not None
                                   and r["dist_to_osm_arch_m"] <= 100),
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


def build_matrix(rows, feats, cw, kw, desc):
    """Feature matrix for logistic regression: booleans + continuous + scalars."""
    names = list(feats) + [n for n, _ in CONTINUOUS] + ["class_w", "keyword_w"]
    X = np.zeros((len(rows), len(names)))
    for i, r in enumerate(rows):
        j = 0
        for _n, f in feats.items():
            X[i, j] = 1.0 if f(r) else 0.0
            j += 1
        for _n, f in CONTINUOUS:
            X[i, j] = f(r)
            j += 1
        X[i, j] = cw.get(r["dominant_class"] or "?", 0.0); j += 1
        X[i, j] = keyword_bonus(r["cluster_id"], desc, kw)
    return X, names


def fit_logistic(rows, feats, cw, kw, desc, positives, negatives, train_pos,
                 seed=1, neg_sample=40000):
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
    X, names = build_matrix(train_rows, feats, cw, kw, desc)
    Xs, mu, sd = LR.standardise(X)
    w, b = LR.fit(Xs, y, sample_weight=sw, l2=5.0, iters=4000)
    return w, b, mu, sd, names


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--seed", type=int, default=1)
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
             **SIZE_FEATURES, **NOTABILITY_FEATURES}
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
                            pos_all, neg_all, train, seed=args.seed)
    w_lr, b_lr, mu, sd, names = lr_model
    top = sorted(zip(names, w_lr), key=lambda x: -abs(x[1]))[:12]
    print("  pesos mas fuertes (decorrelacionados):")
    for n_, v in top:
        print(f"    {n_:<18}{v:+.3f}")

    def full_score(r):
        return (score_of(r, feats, weights)
                + cw.get(r["dominant_class"] or "?", 0.0)
                + keyword_bonus(r["cluster_id"], desc, kw))

    # --- evaluate the honest score on held-out positives ------------------- #
    eval_rows = [r for r in fit_rows
                 if r["cluster_id"] not in train]          # drop train leakage
    Xe, _ = build_matrix(eval_rows, feats, cw, kw, desc)
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
    Xa, _ = build_matrix(rows, feats, cw, kw, desc)
    lr_all = LR.predict((Xa - mu) / sd, w_lr, b_lr)

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
        full = intrinsic + score_of(r, LABEL_DERIVED, lw)
        hard = int(bool(r["class_blacklisted"]))
        # Soft exclusion, with the escape hatch: any independent positive
        # evidence rescues a Stensattning cluster.
        rescued = (bool(r["has_name"]) or (r["sitelinks"] or 0) > 0
                   or bool(r["has_image"])
                   or (r["dist_to_board_m"] is not None
                       and r["dist_to_board_m"] <= 500))
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
