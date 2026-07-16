# Context event-reserve combined development screen

> **Scope:** Four-scenario development-only evidence; no paper, locked-test, or SOTA claim is permitted.

- Config SHA-256: `adda8cf0175ccac6a469e71ead1b3ec66ab96a4cfcd3d6dd98a80e41a4338e86`
- Design: 4 scenarios × 10 roots × 3 workloads = 120 paired cells per method
- Independent observations: 10 root clusters (12 cells per cluster)
- Audit: **PASS**
- Recommendation: **`NO_GO_EVENTRESERVE_DEVELOPMENT_SCREEN_FAILED`**

## Root-cluster paired effects

| Comparator | Mean Δ tasks | Mean Δ% | 95% cluster CI | Root W/T/L | raw p> | Holm p> |
|---|---:|---:|---:|---:|---:|---:|
| `bootstrap_only` | +115.61 | +2.90% | [+1.46%, +4.48%] | 9/0/1 | 0.001953 | 0.007812 |
| `exact_even_B25` | -65.26 | -1.17% | [-1.71%, -0.62%] | 1/0/9 | 0.998 | 1 |
| `context_memory_B25` | -14.38 | -0.37% | [-0.58%, -0.18%] | 1/0/9 | 0.998 | 1 |
| `context_dualcap_G4S5` | +3.86 | +0.10% | [-0.07%, +0.27%] | 7/0/3 | 0.1562 | 0.4688 |

## Resource summary

| Method | Mean tasks | Generator calls | Post generations | Post switches |
|---|---:|---:|---:|---:|
| `exact_even_B25` | 4603.59 | 26.00 | 25.00 | 25.00 |
| `bootstrap_only` | 4422.73 | 1.00 | 0.00 | 0.00 |
| `context_memory_B25` | 4552.72 | 5.38 | 4.38 | 6.08 |
| `context_dualcap_G4S5` | 4534.48 | 4.45 | 3.45 | 4.37 |
| `context_eventreserve_G5S6` | 4538.33 | 4.92 | 3.92 | 4.72 |

## Frozen screen gates

- PASS — `audit_all_passed`
- PASS — `eventreserve_vs_bootstrap_mean_at_least_2pct`
- PASS — `eventreserve_vs_bootstrap_ci_lower_strictly_positive`
- PASS — `eventreserve_vs_bootstrap_exact_sign_flip_p_greater_below_0_05`
- FAIL — `eventreserve_vs_bootstrap_all_10_roots_positive`
- FAIL — `eventreserve_vs_exact_mean_at_least_minus_0_5pct`
- FAIL — `eventreserve_vs_exact_ci_lower_strictly_above_minus_1pct`
- PASS — `eventreserve_vs_context_mean_at_least_minus_1pct`
- PASS — `eventreserve_vs_context_ci_lower_strictly_above_minus_1pct`
- PASS — `generator_call_reduction_vs_exact_at_least_80pct`
- PASS — `mean_post_bootstrap_switches_at_most_5`

Event-reserve vs dual-cap point estimate: +0.10% (better=True; not a gate).

A full pass only licenses fresh validation-v3 of the unchanged candidate.
