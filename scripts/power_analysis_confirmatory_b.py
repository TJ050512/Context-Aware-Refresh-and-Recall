#!/usr/bin/env python3
"""Power analysis for a higher-power confirmatory replication (experiment B).

Motivation
----------
The frozen A2 confirmation FAILED the pre-registered 1% non-inferiority test of
``context_memory_B25`` (CARR) versus ``exact_even_B25`` (dense refresh):

    mean relative effect = -0.4009%
    95% whole-root bootstrap CI = [-1.0834%, +0.2584%]
    shifted one-sided exact sign-flip p = 0.06836

The test requires ALL THREE registered conditions:
    (a) mean effect >= -0.50%
    (b) CI lower bound strictly above -1.00%
    (c) shifted one-sided exact p < 0.05

A2 PASSED (a) but FAILED (b) and (c). Conditions (b) and (c) are pure
statistical-power problems: with only 10 root clusters the interval is too wide
and the exact sign-flip test has only 2^10 = 1024 assignments. This script uses
the REAL A2 per-root effects to estimate how many fresh roots a replication
needs, and which condition is binding at each sample size.

This is a PLANNING tool. It does not touch frozen artifacts and must not be
confused with the frozen confirmatory analyzer. It uses a normal approximation
to the percentile-bootstrap CI and to the exact sign-flip p-value, which is
accurate for n >= ~15 on these roughly symmetric root effects.
"""

from __future__ import annotations

import math
import random

# Real A2 root-level relative effects of context_memory_B25 minus exact_even_B25,
# copied verbatim from reports/same_call_confirmation_a2_analysis.json
# (noninferiority_vs_exact_even_B25.comparison.root_relative_effects).
A2_ROOT_EFFECTS = [
    -0.013260312063482388,  # 691817
    -0.0024858395027416587,  # 376110
    -0.025236335112064346,  # 263001
    -0.0013485522877374305,  # 293231
    0.004041743749304523,   # 296805
    0.006242072721081506,   # 274330
    0.014689069351204816,   # 997942
    -0.0004090394549435531,  # 319782
    -0.014379032715747414,  # 807287
    -0.007946298351205213,  # 326454
]

# Registered non-inferiority rule (unchanged from A2; must not be relaxed).
MARGIN = -0.01           # -1% non-inferiority margin
MEAN_GATE = -0.005       # condition (a): mean effect >= -0.5%
ALPHA = 0.05             # condition (c): shifted one-sided p < 0.05
Z_95 = 1.959963985       # two-sided 95% -> percentile-bootstrap CI lower via normal approx

N_SIMS = 8000
RNG_SEED = 20260715
_SQRT2 = math.sqrt(2.0)


def normal_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / _SQRT2)


def ni_pass(sample: list) -> tuple:
    """Return (cond_a, cond_b, cond_c) for one simulated root-effect sample."""
    n = len(sample)
    s = 0.0
    for x in sample:
        s += x
    m = s / n
    var = 0.0
    for x in sample:
        d = x - m
        var += d * d
    var /= (n - 1)
    se = math.sqrt(var / n)

    cond_a = m >= MEAN_GATE
    cond_b = (m - Z_95 * se) > MARGIN

    # Shifted one-sided sign-flip under H0: true effect == MARGIN (-1%).
    # Shift so the null mean is 0, then normal-approx the sign-flip null:
    # mean(S o v) has mean 0 and SE = sqrt(sum v^2)/n under sign symmetry.
    sv = 0.0
    ssq = 0.0
    for x in sample:
        vv = x - MARGIN
        sv += vv
        ssq += vv * vv
    mean_v = sv / n
    ss = math.sqrt(ssq) / n
    if ss == 0.0:
        cond_c = mean_v > 0.0
    else:
        cond_c = (1.0 - normal_cdf(mean_v / ss)) < ALPHA
    return cond_a, cond_b, cond_c


def simulate_power(n: int, true_theta: float, residuals: list[float], rng: random.Random):
    a = b = c = passed = 0
    for _ in range(N_SIMS):
        sample = [true_theta + rng.choice(residuals) for _ in range(n)]
        ca, cb, cc = ni_pass(sample)
        a += ca
        b += cb
        c += cc
        passed += ca and cb and cc
    return a / N_SIMS, b / N_SIMS, c / N_SIMS, passed / N_SIMS


def main() -> None:
    n0 = len(A2_ROOT_EFFECTS)
    mean = sum(A2_ROOT_EFFECTS) / n0
    sd = math.sqrt(sum((x - mean) ** 2 for x in A2_ROOT_EFFECTS) / (n0 - 1))
    residuals = [x - mean for x in A2_ROOT_EFFECTS]

    print("=" * 78)
    print("A2 empirical per-root effect (CARR - dense refresh), n=10")
    print(f"  mean = {mean*100:+.4f}%   sd = {sd*100:.4f}%   se = {sd/math.sqrt(10)*100:.4f}%")
    print("  A2 outcome: (a) PASS  (b) FAIL  (c) FAIL  -> NI FAIL")
    print("=" * 78)
    print()
    print("Simulated NI power via residual bootstrap of the REAL A2 residuals.")
    print("Rows: assumed TRUE effect (theta). Cols: number of fresh roots.")
    print("Each cell: overall P(pass all 3) and, in [], the binding condition rates.")
    print(f"n_sims={N_SIMS}, margin={MARGIN*100:.1f}%, mean_gate={MEAN_GATE*100:.1f}%, seed={RNG_SEED}")
    print()

    ns = [15, 20, 25, 30, 40, 50]
    thetas = [0.0, -0.001, -0.002, -0.003, -0.004, -0.005]

    header = "true theta |" + "".join(f"  n={n:<3d}" for n in ns)
    print(header)
    print("-" * len(header))
    for theta in thetas:
        rng = random.Random(RNG_SEED + int(round(theta * 1e6)))
        cells = []
        for n in ns:
            _, _, _, power = simulate_power(n, theta, residuals, rng)
            cells.append(power)
        row = f"{theta*100:+6.2f}%    |" + "".join(f"  {p*100:5.1f}" for p in cells)
        print(row)
    print()

    print("Per-condition breakdown at the two candidate sample sizes")
    print("(shows WHICH gate is binding; theta = assumed true effect):")
    for n in (30, 40):
        print(f"\n  n = {n} fresh roots:")
        print("    theta   P(a: mean>=-0.5%)  P(b: CI>-1%)  P(c: p<0.05)  P(all)")
        for theta in thetas:
            rng = random.Random(RNG_SEED + 7 + int(round(theta * 1e6)))
            pa, pb, pc, pall = simulate_power(n, theta, residuals, rng)
            print(f"   {theta*100:+5.2f}%      {pa*100:6.1f}          {pb*100:6.1f}       {pc*100:6.1f}      {pall*100:6.1f}")


if __name__ == "__main__":
    main()
