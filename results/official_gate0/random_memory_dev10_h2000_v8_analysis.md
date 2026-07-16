# Random-memory v8 development ablation

> Development evidence only. This report does not authorize a formal or SOTA claim.

## Integrity and audit

- Artifact SHA-256: `ac8f186cf4441b3e130e3e5dcd5057196b9ab4a892d5aeeb90482ccfb4553a09`
- Complete paired grid: **PASS**
- Safety/invariant audit: **PASS**
- Local map hash verification: **PASS**
- Random-opportunity identity: **PASS**

All 30 random/random-memory cells share the same 99 decision flags and 25 accepted random opportunities.

## Root-seed-cluster inference

| Comparator | Δ tasks | Δ mean % | 95% cluster CI | Exact p (two-sided) | Exact p (memory > baseline) |
|---|---:|---:|---:|---:|---:|
| `random_B25` | 0.03 | 0.001% | [-24.10, 24.40] | 1 | 0.5 |
| `exact_even_B25` | 62.63 | 1.519% | [-26.67, 151.10] | 0.2246 | 0.1123 |

## Per-workload effects

### Memory minus random_B25

| Workload | Memory tasks | Baseline tasks | Δ tasks | Δ % | W/T/L cells |
|---|---:|---:|---:|---:|---:|
| stationary | 3549.50 | 3550.10 | -0.60 | -0.017% | 0/9/1 |
| abrupt | 4556.10 | 4580.00 | -23.90 | -0.522% | 0/9/1 |
| recurrent | 4454.30 | 4429.70 | 24.60 | 0.555% | 1/9/0 |

### Memory minus exact_even_B25

| Workload | Memory tasks | Baseline tasks | Δ tasks | Δ % | W/T/L cells |
|---|---:|---:|---:|---:|---:|
| stationary | 3549.50 | 3474.20 | 75.30 | 2.167% | 7/0/3 |
| abrupt | 4556.10 | 4318.40 | 237.70 | 5.504% | 7/0/3 |
| recurrent | 4454.30 | 4579.40 | -125.10 | -2.732% | 3/0/7 |

## Recall and generation savings

- Reactivations: 3 / 750 opportunities (0.400%).
- Runs containing recall: 3 / 30.
- Generator calls: 780 → 777 (saved 3, 0.385%).
- All 27 non-recall cells reproduced identical task counts.
- Wall-clock timing is not claimable because the run used parallel jobs without exclusive timing.

| Seed | Workload | Decision | Target generation | Δ tasks | Calls saved |
|---:|---|---:|---:|---:|---:|
| 20 | abrupt | 16 | 1 | -239 | 1 |
| 22 | stationary | 99 | 20 | -6 | 1 |
| 25 | recurrent | 63 | 7 | 246 | 1 |

## Recommendation

**negative_ablation_not_a_formal_candidate**.

- Random opportunities are exactly matched, so the ablation is causally interpretable.
- Recall occurred at only 3 of 750 opportunities (0.400%).
- The mean throughput/task effect versus random is effectively zero and its seed-cluster confidence interval spans harm and benefit.
- Only three generator calls were saved across 30 runs, while the three recalled cells had large mixed effects that cancelled.
- It is useful as evidence that naive nearest-context recall grafted onto random timing is insufficient; redesign would constitute a new development candidate rather than a reason to test this v8 arm formally.
