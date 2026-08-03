#!/usr/bin/env python3
"""Train CARR-RL-lite: a lightweight learned hold/generate controller.

Two feature sets are compared to answer "is rule-based CARR already near a
learned controller, and are the four proposed raw features sufficient?":

  * raw4      : GPT's proposed lightweight inputs
                (js_change, age, adoption, context_distance)
  * fullstate : raw4 + the controller's causal internal state
                (score, threshold, persistence_count, spent_before,
                 remaining_epochs_after, maintenance_due, route_mature,
                 action_available, minimum_score)

Both use seed-grouped 5-fold CV (no seed in both train/val) to avoid leakage.

Outputs <out>/policy.json (frozen linear policy for raw4) and <out>/report.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

RAW4 = ("js_change", "age", "adoption", "context_distance")
EXTRA = (
    "score",
    "threshold",
    "persistence_count",
    "spent_before",
    "remaining_epochs_after",
    "maintenance_due",
    "route_mature",
    "action_available",
    "minimum_score",
)


def _load(path: Path):
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def _feats(rows, names):
    X = []
    for r in rows:
        row = []
        for n in names:
            v = r.get(n)
            if v is None:
                v = 0.0
            if isinstance(v, bool):
                v = 1.0 if v else 0.0
            row.append(float(v))
        X.append(row)
    return np.array(X, dtype=float)


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _train(X, y, lr=0.5, epochs=4000, l2=1e-3, cw=None):
    n, d = X.shape
    w = np.zeros(d)
    b = 0.0
    cw = np.ones(n) if cw is None else cw
    for _ in range(epochs):
        p = _sigmoid(X @ w + b)
        err = (p - y) * cw
        w -= lr * ((X.T @ err) / n + l2 * w)
        b -= lr * err.mean()
    return w, b


def _auc(y, p):
    o = np.argsort(p)
    ys = y[o]
    P = ys.sum()
    N = len(ys) - P
    if P == 0 or N == 0:
        return None
    ranks = np.empty(len(ys))
    ranks[o] = np.arange(1, len(ys) + 1)
    return float((ranks[ys == 1].sum() - P * (P + 1) / 2) / (P * N))


def _cv(rows, names, seeds):
    X = _feats(rows, names)
    mu = X.mean(0)
    sd = X.std(0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd
    y = np.array([1.0 if r["rule_accepted"] else 0.0 for r in rows])
    pos = y.sum()
    neg = len(y) - pos
    cw = np.where(y == 1, len(y) / (2 * max(pos, 1)), len(y) / (2 * max(neg, 1)))
    uniq = np.unique(seeds)
    folds = np.array_split(uniq, 5)
    ag, au, pcr = [], [], []
    for vs in folds:
        vm = np.isin(seeds, vs)
        w, b = _train(Xs[~vm], y[~vm], cw=cw[~vm])
        p = _sigmoid(Xs[vm] @ w + b)
        pr = (p >= 0.5).astype(float)
        ag.append(float((pr == y[vm]).mean()))
        a = _auc(y[vm], p)
        if a is not None:
            au.append(a)
        pcr.append(float(pr.mean()))
    w_full, b_full = _train(Xs, y, cw=cw)
    return {
        "features": list(names),
        "mean": mu.tolist(),
        "std": sd.tolist(),
        "weights": w_full.tolist(),
        "bias": float(b_full),
        "cv_agreement_mean": float(np.mean(ag)),
        "cv_auc_mean": (float(np.mean(au)) if au else None),
        "cv_predicted_call_rate_mean": float(np.mean(pcr)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = _load(Path(args.data))
    seeds = np.array([r["seed"] for r in rows])
    y = np.array([1.0 if r["rule_accepted"] else 0.0 for r in rows])

    res_raw4 = _cv(rows, RAW4, seeds)
    res_full = _cv(rows, RAW4 + EXTRA, seeds)

    policy = {
        "schema": "dai.carr-rl-lite/v1",
        "features": res_raw4["features"],
        "standardize": {"mean": res_raw4["mean"], "std": res_raw4["std"]},
        "weights": res_raw4["weights"],
        "bias": res_raw4["bias"],
        "decision_threshold": 0.5,
    }
    (out / "policy.json").write_text(json.dumps(policy, indent=2))

    report = {
        "n_decision_rows": int(len(y)),
        "n_seeds": int(len(np.unique(seeds))),
        "rule_accept_rate": float(y.mean()),
        "raw4": {k: res_raw4[k] for k in ("cv_agreement_mean", "cv_auc_mean", "cv_predicted_call_rate_mean")},
        "fullstate": {k: res_full[k] for k in ("cv_agreement_mean", "cv_auc_mean", "cv_predicted_call_rate_mean")},
        "interpretation": (
            "raw4 ~0.5 AUC means the four proposed raw features alone cannot "
            "reproduce the rule; fullstate high AUC means the rule is a smooth "
            "function of its causal state (score vs running threshold)."
        ),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
