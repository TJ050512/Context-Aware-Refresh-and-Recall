# Same-call confirmation B

- Audit: **PASS**
- Outcome: **TIER_C_NO_GO_CURRENT_CONTEXT_MEMORY_PAPER**
- Config SHA-256: `44127caa81272e7fb15fcbf33a9d430222c869238cf87e35280f4c0f3fc4f112`
- Independent observations: 40 root clusters; 12 equally weighted cells per root and method

## Six frozen superiority contrasts

| Comparator | Mean Δ% | 95% root CI | Root W/T/L | raw p> | Holm p> |
|---|---:|---:|---:|---:|---:|
| `bootstrap_only` | +4.42% | [+3.75%, +5.07%] | 40/0/0 | 9.095e-13 | 5.457e-12 |
| `exact_even_G4` | +2.17% | [+1.77%, +2.59%] | 37/0/3 | 7.276e-12 | 2.91e-11 |
| `exact_even_G5` | +0.75% | [+0.32%, +1.18%] | 28/0/12 | 0.0007661 | 0.001532 |
| `random_G5` | +1.69% | [+1.27%, +2.11%] | 36/0/4 | 1.124e-09 | 3.372e-09 |
| `js_cap_G5` | +3.36% | [+2.85%, +3.87%] | 39/0/1 | 1.819e-12 | 9.095e-12 |
| `context_no_reactivation_B25` | -0.11% | [-0.26%, +0.03%] | 18/0/22 | 0.925 | 0.925 |

## Separate 1% non-inferiority test

- Mean Δ: -0.80%
- 95% root CI: [-1.19%, -0.40%]
- Shifted one-sided exact p: 0.1693
- Result: **FAIL**

## Calls and Pareto points

| Method | Mean tasks | Calls mean/median/P90/max | Calls ≤5 / ≤6 | Post generations mean | Switches mean | Reactivations mean |
|---|---:|---:|---:|---:|---:|---:|
| `bootstrap_only` | 4355.08 | 1.00/1.00/1.00/1 | 100.0% / 100.0% | 0.00 | 0.00 | 0.00 |
| `exact_even_G4` | 4451.10 | 5.00/5.00/5.00/5 | 100.0% / 100.0% | 4.00 | 4.00 | 0.00 |
| `exact_even_G5` | 4505.35 | 6.00/6.00/6.00/6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 |
| `random_G5` | 4465.94 | 6.00/6.00/6.00/6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 |
| `js_cap_G5` | 4391.32 | 6.00/6.00/6.00/6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 |
| `context_no_reactivation_B25` | 4544.06 | 7.07/7.00/10.00/13 | 33.5% / 49.4% | 6.07 | 6.07 | 0.00 |
| `context_memory_B25` | 4539.62 | 5.46/5.00/8.00/10 | 61.5% / 76.0% | 4.46 | 6.20 | 1.74 |
| `exact_even_B25` | 4588.90 | 26.00/26.00/26.00/26 | 0.0% / 0.0% | 25.00 | 25.00 | 0.00 |

Pareto frontier: `bootstrap_only`, `exact_even_G4`, `context_no_reactivation_B25`, `context_memory_B25`, `exact_even_B25`

## Mechanical tier checks

- PASS — Tier B `all_audits_pass`
- PASS — Tier B `bootstrap_mean_at_least_2pct`
- PASS — Tier B `bootstrap_ci_lower_above_zero`
- PASS — Tier B `bootstrap_holm_p_below_0_05`
- FAIL — Tier B `exact_b25_1pct_noninferiority`
- PASS — Tier B `mean_calls_at_most_6`
- PASS — Tier B `call_reduction_at_least_75pct`
- PASS — Tier B `focal_not_point_dominated`
- PASS — Tier B `bootstrap_positive_both_maps`
- PASS — Tier B `bootstrap_positive_all_workloads`
- PASS — Tier B `zero_selective_deletion`
- FAIL — Tier A `all_six_holm_p_below_0_05`
- FAIL — Tier A `all_six_ci_lower_above_zero`
- PASS — Tier A `all_sparse_control_means_positive`
- FAIL — Tier A `historical_recall_mean_positive`
- PASS — Tier A `g5_positive_both_maps`
- PASS — Tier A `g5_positive_at_least_two_workloads`
- PASS — Tier A `g5_stationary_degradation_no_worse_than_1pct`
