# Full development matrix analysis

Candidate: `context_memory_B25`. Source split: `development`. 

> **Scope:** Development screening only; do not report as locked-test, confirmatory, paper-grade SOTA, or global LMAPF SOTA evidence.

The complete paired grid contains 390 runs: 13 methods × 10 root seeds × 1 maps × 3 workloads. Inference clusters by root seed.

Pairing audit: **PASS**. Zero safety/invalid outcomes: **PASS**.

## Macro ranking

| Rank | Method | Mean tasks | Post pubs | Generator calls |
|---:|---|---:|---:|---:|
| 1 | `random_B25` | 4262.30 | 25.00 | 26.00 |
| 2 | `causal_block_B25` | 4238.33 | 25.00 | 26.00 |
| 3 | `proposed_no_cohort_B25` | 4209.23 | 25.00 | 26.00 |
| 4 | `context_memory_B25` | 4195.20 | 3.90 | 4.73 |
| 5 | `js_B25` | 4186.10 | 25.00 | 26.00 |
| 6 | `proposed_cohort_B25` | 4172.73 | 25.00 | 26.00 |
| 7 | `period_80` | 4171.07 | 24.00 | 25.00 |
| 8 | `exact_even_B25` | 4169.77 | 25.00 | 26.00 |
| 9 | `js_cap_B25` | 4163.83 | 20.53 | 21.53 |
| 10 | `throughput_drop_B25` | 4156.63 | 25.00 | 26.00 |
| 11 | `always` | 4151.57 | 99.00 | 100.00 |
| 12 | `bootstrap_only` | 4070.47 | 0.00 | 1.00 |
| 13 | `uniform` | 2444.33 | 0.00 | 0.00 |

## Per-workload rankings

### stationary

| Rank | Method | Mean tasks |
|---:|---|---:|
| 1 | `random_B25` | 3587.00 |
| 2 | `causal_block_B25` | 3579.20 |
| 3 | `throughput_drop_B25` | 3575.20 |
| 4 | `proposed_cohort_B25` | 3567.40 |
| 5 | `js_B25` | 3566.70 |
| 6 | `js_cap_B25` | 3546.60 |
| 7 | `proposed_no_cohort_B25` | 3543.30 |
| 8 | `context_memory_B25` | 3510.70 |
| 9 | `always` | 3501.30 |
| 10 | `period_80` | 3496.30 |
| 11 | `exact_even_B25` | 3495.30 |
| 12 | `bootstrap_only` | 3399.00 |
| 13 | `uniform` | 2220.60 |

### abrupt

| Rank | Method | Mean tasks |
|---:|---|---:|
| 1 | `causal_block_B25` | 4539.30 |
| 2 | `random_B25` | 4525.60 |
| 3 | `period_80` | 4470.70 |
| 4 | `exact_even_B25` | 4470.60 |
| 5 | `context_memory_B25` | 4448.40 |
| 6 | `proposed_no_cohort_B25` | 4437.30 |
| 7 | `js_B25` | 4415.70 |
| 8 | `throughput_drop_B25` | 4400.70 |
| 9 | `always` | 4398.10 |
| 10 | `proposed_cohort_B25` | 4397.10 |
| 11 | `bootstrap_only` | 4368.40 |
| 12 | `js_cap_B25` | 4366.60 |
| 13 | `uniform` | 2552.90 |

### recurrent

| Rank | Method | Mean tasks |
|---:|---|---:|
| 1 | `random_B25` | 4674.30 |
| 2 | `proposed_no_cohort_B25` | 4647.10 |
| 3 | `context_memory_B25` | 4626.50 |
| 4 | `causal_block_B25` | 4596.50 |
| 5 | `js_cap_B25` | 4578.30 |
| 6 | `js_B25` | 4575.90 |
| 7 | `always` | 4555.30 |
| 8 | `proposed_cohort_B25` | 4553.70 |
| 9 | `period_80` | 4546.20 |
| 10 | `exact_even_B25` | 4543.40 |
| 11 | `throughput_drop_B25` | 4494.00 |
| 12 | `bootstrap_only` | 4444.00 |
| 13 | `uniform` | 2559.50 |

## Candidate pairwise inference

Effects are candidate minus comparator. Bootstrap intervals resample whole root-seed clusters; p-values use all exact sign assignments.

| Comparator | Δ tasks | Δ % | 95% CI tasks | W/T/L seeds | p> raw | p> Holm | p2 Holm |
|---|---:|---:|---:|---:|---:|---:|---:|
| `random_B25` | -67.10 | -1.57% | [-145.07, 10.20] | 4/0/6 | 0.9258 | 1 | 1 |
| `causal_block_B25` | -43.13 | -1.02% | [-111.60, 27.27] | 3/0/7 | 0.8623 | 1 | 1 |
| `proposed_no_cohort_B25` | -14.03 | -0.33% | [-99.13, 70.03] | 5/0/5 | 0.6182 | 1 | 1 |
| `js_B25` | 9.10 | 0.22% | [-105.80, 119.50] | 5/0/5 | 0.4443 | 1 | 1 |
| `proposed_cohort_B25` | 22.47 | 0.54% | [-60.17, 105.64] | 5/0/5 | 0.3105 | 1 | 1 |
| `period_80` | 24.13 | 0.58% | [-86.30, 137.77] | 5/0/5 | 0.3486 | 1 | 1 |
| `exact_even_B25` | 25.43 | 0.61% | [-85.17, 139.03] | 5/0/5 | 0.3389 | 1 | 1 |
| `js_cap_B25` | 31.37 | 0.75% | [-78.94, 134.74] | 7/0/3 | 0.2988 | 1 | 1 |
| `throughput_drop_B25` | 38.57 | 0.93% | [-53.40, 136.80] | 4/0/6 | 0.2344 | 1 | 1 |
| `always` | 43.63 | 1.05% | [-42.13, 131.40] | 6/0/4 | 0.1787 | 1 | 1 |
| `bootstrap_only` | 124.73 | 3.06% | [59.20, 194.77] | 9/0/1 | 0.003906 | 0.04297 | 0.08594 |
| `uniform` | 1750.87 | 71.63% | [1593.93, 1888.54] | 10/0/0 | 0.0009766 | 0.01172 | 0.02344 |

## Pareto frontiers

- tasks_vs_post_bootstrap_publications: `bootstrap_only`, `context_memory_B25`, `random_B25`
- tasks_vs_total_generator_calls: `uniform`, `bootstrap_only`, `context_memory_B25`, `random_B25`

## Random-baseline driver diagnostic

Mean random advantage: 67.10 tasks. Random cell W/T/L: 20/0/10.

Seed diagnosis: `broad_across_seeds_and_not_reversed_by_any_single_seed`; workload diagnosis: `broad_across_workloads`.

| Seed | Random − candidate tasks |
|---:|---:|
| 17 | 287.00 |
| 18 | 209.00 |
| 19 | -56.00 |
| 20 | -148.33 |
| 21 | 121.00 |
| 22 | 18.00 |
| 23 | -19.33 |
| 24 | -5.33 |
| 25 | 93.00 |
| 26 | 172.00 |

| Workload | Random − candidate tasks |
|---|---:|
| stationary | 76.30 |
| abrupt | 77.20 |
| recurrent | 47.80 |

## Interpretation guardrail

A development-set rank is useful for method selection, not for a confirmatory superiority or SOTA claim. Freeze the selected controller before evaluating fresh validation and locked-test seeds/maps.
