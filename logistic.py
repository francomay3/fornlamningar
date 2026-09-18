#!/usr/bin/env python3
"""
L2-regularised logistic regression, numpy only.

Why this exists: the log-lift ("naive Bayes") weights assume the features are
INDEPENDENT, and they are not. `has_name`, `desc_gt_300` and `dim_h>1m` all
correlate, so summing their log-lifts counts the same evidence three times.
Logistic regression fits the features jointly, so shared evidence is credited
once and each weight means "what this feature adds on top of the others".

It also uses verified NEGATIVES, which the lift estimator has no slot for — it
could only ever compare positives against the base rate.

No scipy: plain gradient descent with momentum converges fine at this size
(~250k rows, ~25 features).
"""

import numpy as np


def fit(X, y, sample_weight=None, l2=1.0, iters=4000, lr=0.5, verbose=False):
    """Return (weights, bias). X is (n, d) float64, y is 0/1."""
    n, d = X.shape
    w = np.zeros(d)
    b = 0.0
    sw = np.ones(n) if sample_weight is None else np.asarray(sample_weight,
                                                             dtype=np.float64)
    sw = sw / sw.mean()
    vw = np.zeros(d)
    vb = 0.0
    mom = 0.9
    for it in range(iters):
        z = X @ w + b
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        resid = (p - y) * sw
        gw = X.T @ resid / n + l2 * w / n
        gb = resid.sum() / n
        vw = mom * vw - lr * gw
        vb = mom * vb - lr * gb
        w += vw
        b += vb
        if verbose and it % 1000 == 0:
            ll = -np.mean(sw * (y * np.log(p + 1e-12)
                                + (1 - y) * np.log(1 - p + 1e-12)))
            print(f"    iter {it:>5}  loss {ll:.5f}")
    return w, b


def predict(X, w, b):
    return 1.0 / (1.0 + np.exp(-np.clip(X @ w + b, -30, 30)))


def logit(X, w, b):
    """The linear predictor, before the sigmoid.

    For RANKING this is what you want, and the difference is not cosmetic.
    The sigmoid saturates: everything the model is confident about lands on
    1.0 and ties. Measured on 2026-09-18, 2,000 places shared the identical
    top score and 62.3% of all runestones sat on the ceiling -- inside that
    block there was no ordering at all, so "which runestone is worth the
    detour" had no answer the data could give.

    The log-odds is monotone in the probability, so it ranks identically
    wherever the probability discriminates, and it keeps discriminating where
    the probability has run out of resolution. AUC is unchanged by
    construction; what changes is that the ties disappear.
    """
    return X @ w + b


def standardise(X):
    """Zero mean, unit variance per column. Returns (Xs, mu, sd)."""
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd, mu, sd


def auc(scores, labels):
    """Rank-based AUC with tie handling."""
    s = np.asarray(scores, dtype=np.float64)
    y = np.asarray(labels)
    order = np.argsort(s)
    s_sorted = s[order]
    y_sorted = y[order]
    ranks = np.empty(len(s), dtype=np.float64)
    i = 0
    while i < len(s):
        j = i
        while j < len(s) and s_sorted[j] == s_sorted[i]:
            j += 1
        ranks[i:j] = (i + j + 1) / 2.0
        i = j
    npos = y_sorted.sum()
    nneg = len(y) - npos
    if npos == 0 or nneg == 0:
        return float("nan")
    return (ranks[y_sorted == 1].sum() - npos * (npos + 1) / 2.0) / (npos * nneg)
