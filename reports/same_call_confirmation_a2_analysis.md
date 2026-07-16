# Same-call confirmation v1

- Audit: **PASS**
- Outcome: **TIER_C_NO_GO_CURRENT_CONTEXT_MEMORY_PAPER**
- Config SHA-256: `e0763c409c900bbc21e9b69fff5e978261a89cba8ad883d16ef705d012c9d96f`
- Independent observations: 10 root clusters; 12 equally weighted cells per root and method

## Six frozen superiority contrasts

| Comparator | Mean Δ% | 95% root CI | Root W/T/L | raw p> | Holm p> |
|---|---:|---:|---:|---:|---:|
| `bootstrap_only` | +3.72% | [+3.04%, +4.44%] | 10/0/0 | 0.0009766 | 0.005859 |
| `exact_even_G4` | +2.04% | [+1.40%, +2.67%] | 10/0/0 | 0.0009766 | 0.005859 |
| `exact_even_G5` | +0.17% | [-0.33%, +0.61%] | 7/0/3 | 0.2588 | 0.5176 |
| `random_G5` | +1.22% | [+0.14%, +2.52%] | 6/0/4 | 0.03906 | 0.1172 |
| `js_cap_G5` | +3.11% | [+2.32%, +3.93%] | 10/0/0 | 0.0009766 | 0.005859 |
| `context_no_reactivation_B25` | -0.11% | [-0.48%, +0.21%] | 5/0/5 | 0.708 | 0.708 |

## Separate 1% non-inferiority test

- Mean Δ: -0.40%
- 95% root CI: [-1.08%, +0.26%]
- Shifted one-sided exact p: 0.06836
- Result: **FAIL**

## Calls and Pareto points

| Method | Mean tasks | Calls mean/median/P90/max | Calls ≤5 / ≤6 | Post generations mean | Switches mean | Reactivations mean |
|---|---:|---:|---:|---:|---:|---:|
| `bootstrap_only` | 4417.02 | 1.00/1.00/1.00/1 | 100.0% / 100.0% | 0.00 | 0.00 | 0.00 |
| `exact_even_G4` | 4485.12 | 5.00/5.00/5.00/5 | 100.0% / 100.0% | 4.00 | 4.00 | 0.00 |
| `exact_even_G5` | 4562.68 | 6.00/6.00/6.00/6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 |
| `random_G5` | 4516.89 | 6.00/6.00/6.00/6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 |
| `js_cap_G5` | 4428.62 | 6.00/6.00/6.00/6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 |
| `context_no_reactivation_B25` | 4577.10 | 6.98/6.50/10.00/13 | 36.7% / 50.0% | 5.98 | 5.98 | 0.00 |
| `context_memory_B25` | 4571.32 | 5.47/5.00/8.00/12 | 60.8% / 78.3% | 4.47 | 6.12 | 1.65 |
| `exact_even_B25` | 4598.92 | 26.00/26.00/26.00/26 | 0.0% / 0.0% | 25.00 | 25.00 | 0.00 |

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
- FAIL — Tier A `g5_positive_both_maps`
- PASS — Tier A `g5_positive_at_least_two_workloads`
- FAIL — Tier A `g5_stationary_degradation_no_worse_than_1pct`
