# Context dual-cap combined development screen

> **Scope:** Four-scenario development-only evidence. Even a full pass cannot support paper results, locked testing, or SOTA claims.

- Frozen config SHA-256: `a8e98493c96fa6c1d521e817b5dd4549f95e8b294588f4b01b50ebe9a995f1a4`
- Design: 4 scenarios × 10 roots × 3 workloads = 120 paired cells per method
- Independent observations: 10 root clusters, not 120 cells
- Audit: **PASS**
- Recommendation: **`NO_GO_COMBINED_DEVELOPMENT_SCREEN_FAILED`**

## Root-cluster paired effects

| Comparator | Mean Δ tasks | Mean Δ% | 95% root-cluster CI | Root W/T/L | p(greater) |
|---|---:|---:|---:|---:|---:|
| `context_memory_B25` | -18.24 | -0.46% | [-0.79%, -0.14%] | 3/0/7 | 0.9854 |
| `exact_even_B25` | -69.12 | -1.26% | [-1.95%, -0.56%] | 1/0/9 | 0.998 |
| `bootstrap_only` | +111.75 | +2.82% | [+1.32%, +4.45%] | 9/0/1 | 0.003906 |

## Resource summary

| Method | Mean tasks | Generator calls | Post generations | Post switches |
|---|---:|---:|---:|---:|
| `exact_even_B25` | 4603.59 | 26.00 | 25.00 | 25.00 |
| `bootstrap_only` | 4422.73 | 1.00 | 0.00 | 0.00 |
| `context_memory_B25` | 4552.72 | 5.38 | 4.38 | 6.08 |
| `context_dualcap_G4S5` | 4534.48 | 4.45 | 3.45 | 4.37 |

## Frozen screen gates

- PASS — `audit_all_passed`
- PASS — `dualcap_vs_bootstrap_mean_relative_effect_at_least_2pct`
- PASS — `dualcap_vs_bootstrap_cluster_ci_lower_strictly_positive`
- PASS — `dualcap_vs_bootstrap_exact_sign_flip_p_greater_below_0_05`
- FAIL — `dualcap_vs_bootstrap_all_10_root_directions_positive`
- FAIL — `dualcap_vs_exact_mean_at_least_minus_0_5pct`
- FAIL — `dualcap_vs_exact_cluster_ci_lower_strictly_above_minus_1pct`
- PASS — `dualcap_vs_context_mean_noninferior_minus_1pct`
- PASS — `dualcap_vs_context_cluster_ci_lower_strictly_above_minus_1pct`
- PASS — `generator_call_reduction_vs_exact_at_least_80pct`
- PASS — `mean_post_bootstrap_switches_at_most_5`

A complete PASS only licenses freezing the unchanged candidate and starting fresh validation-v3. It is not paper, locked-test, or SOTA evidence.
