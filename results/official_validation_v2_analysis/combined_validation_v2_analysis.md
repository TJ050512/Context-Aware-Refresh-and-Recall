# Combined validation-v2 analysis

> **Scope:** This is a ten-root-seed validation freeze analysis. It is not locked-test, confirmatory, or global-SOTA evidence.

Design: 10 root-seed clusters, 2 maps × 2 densities × 3 workloads = 120 paired cells per method. Inference uses **10**, not **120**, independent observations.

Audit: **PASS**; planner timeouts retained as outcomes: 0.

## Macro ranking

| Rank | Method | Mean tasks | Mean throughput | Post pubs | Generator calls |
|---:|---|---:|---:|---:|---:|
| 1 | `proposed_cohort_B25` | 4523.90 | 2.26195 | 25.00 | 26.00 |
| 2 | `js_B25` | 4505.92 | 2.25296 | 25.00 | 26.00 |
| 3 | `js_cap_B25` | 4505.01 | 2.25250 | 22.28 | 23.28 |
| 4 | `proposed_no_cohort_B25` | 4502.69 | 2.25135 | 25.00 | 26.00 |
| 5 | `throughput_drop_B25` | 4499.30 | 2.24965 | 25.00 | 26.00 |
| 6 | `random_B25` | 4493.30 | 2.24665 | 25.00 | 26.00 |
| 7 | `causal_block_B25` | 4490.34 | 2.24517 | 25.00 | 26.00 |
| 8 | `period_80` | 4486.00 | 2.24300 | 24.00 | 25.00 |
| 9 | `exact_even_B25` | 4485.95 | 2.24297 | 25.00 | 26.00 |
| 10 | `always` | 4481.34 | 2.24067 | 99.00 | 100.00 |
| 11 | `context_memory_B25` | 4475.86 | 2.23793 | 6.16 | 5.48 |
| 12 | `bootstrap_only` | 4260.27 | 2.13013 | 0.00 | 1.00 |
| 13 | `uniform` | 2820.51 | 1.41025 | 0.00 | 0.00 |

## Root-cluster paired comparisons

| Comparison | Mean Δ% | 95% cluster CI | Min cell Δ% | W/T/L roots | p> Holm | p2 Holm |
|---|---:|---:|---:|---:|---:|---:|
| `causal_vs_exact` | 0.10% | [-0.58%, 0.71%] | -12.70% | 7/0/3 | 0.7617 | 1 |
| `causal_vs_random` | -0.07% | [-0.87%, 0.85%] | -12.44% | 4/0/6 | 0.7617 | 1 |
| `context_vs_bootstrap` | 5.30% | [3.69%, 7.28%] | -18.58% | 10/0/0 | 0.001953 | 0.003906 |
| `context_vs_exact` | 0.03% | [-0.57%, 0.59%] | -14.80% | 4/0/6 | 0.4678 | 0.9355 |

## Map and workload directions

- `causal_vs_exact` maps — warehouse_small_kiva: positive (0.18%), warehouse_small_narrow_kiva: positive (0.03%)
- `causal_vs_exact` workloads — abrupt: positive (0.54%), recurrent: positive (0.52%), stationary: negative (-0.75%)
- `causal_vs_random` maps — warehouse_small_kiva: negative (-0.32%), warehouse_small_narrow_kiva: positive (0.18%)
- `causal_vs_random` workloads — abrupt: positive (0.51%), recurrent: negative (-0.01%), stationary: negative (-0.70%)
- `context_vs_bootstrap` maps — warehouse_small_kiva: positive (7.36%), warehouse_small_narrow_kiva: positive (3.25%)
- `context_vs_bootstrap` workloads — abrupt: positive (6.22%), recurrent: positive (4.49%), stationary: positive (5.19%)
- `context_vs_exact` maps — warehouse_small_kiva: negative (-0.26%), warehouse_small_narrow_kiva: positive (0.31%)
- `context_vs_exact` workloads — abrupt: positive (0.49%), recurrent: negative (-1.02%), stationary: positive (0.62%)

## Preregistered validation freeze gate

Recommendation: **`NO_GO_RETURN_TO_DEVELOPMENT`**.

- Causal quality path: **FAIL**
- Context validation candidate: **FAIL**
- Context full efficiency claim: **NOT READY** (`validation_candidate_gate_failed`)
- Context near-exact language gate: **PASS**
- Pure-throughput separation: **FAIL** (top `proposed_cohort_B25` vs runner-up `js_B25`)

## Pareto frontiers

- throughput_vs_publications: `bootstrap_only`, `context_memory_B25`, `js_cap_B25`, `proposed_cohort_B25`
- throughput_vs_generator_calls: `uniform`, `bootstrap_only`, `context_memory_B25`, `js_cap_B25`, `proposed_cohort_B25`
- throughput_vs_generator_seconds: `uniform`, `bootstrap_only`, `context_memory_B25`, `js_cap_B25`, `js_B25`, `proposed_cohort_B25`

The gate only decides whether to freeze a candidate before untouched locked testing. It does not license a paper-final or SOTA statement.
