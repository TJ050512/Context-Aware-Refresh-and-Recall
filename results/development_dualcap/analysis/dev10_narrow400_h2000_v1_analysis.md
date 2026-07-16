# Context dual-cap dev10 screen

> **Scope:** Development-only exploratory evidence: this result cannot support a paper-result, locked-test, or SOTA claim.

- Source: `/Users/maxiaoxiao.27/Documents/DAI/research_workspace/results/development_dualcap/dev10_narrow400_h2000_v1.json`
- Source SHA-256: `fc13b2f420dfc80864ca20cd45c4eba09bf9309cc50488437323802879d7b0fb`
- Design: 10 root clusters × 3 workloads = 30 paired cells per method on one map
- Audit: **PASS**
- Recommendation: **`NO_GO_DUALCAP_DEVELOPMENT_SCREEN_FAILED`**

## Paired throughput effects

| Comparator | Mean Δ tasks | Mean Δ% | Root-cluster 95% CI | Root W/T/L | Exact sign-flip p> |
|---|---:|---:|---:|---:|---:|
| `context_memory_B25` | -1.83 | -0.05% | [-0.12%, +0.01%] | 2/6/2 | 0.8125 |
| `exact_even_B25` | +39.27 | +1.07% | [-1.39%, +3.26%] | 7/0/3 | 0.2041 |
| `bootstrap_only` | +87.00 | +2.54% | [+0.50%, +4.60%] | 6/0/4 | 0.02637 |

## Resource summary

| Method | Mean tasks | Generator calls | Post generations | Post switches |
|---|---:|---:|---:|---:|
| `exact_even_B25` | 4124.00 | 26.00 | 25.00 | 25.00 |
| `bootstrap_only` | 4076.27 | 1.00 | 0.00 | 0.00 |
| `context_memory_B25` | 4165.10 | 4.80 | 3.80 | 3.93 |
| `context_dualcap_G4S5` | 4163.27 | 4.67 | 3.67 | 3.80 |

## Screen gates

- PASS — `audit_all_passed`
- FAIL — `vs_bootstrap_all_10_root_directions_positive`
- PASS — `vs_bootstrap_cluster_95ci_lower_strictly_positive`
- PASS — `vs_exact_mean_at_least_minus_1pct`
- FAIL — `vs_exact_cluster_95ci_lower_strictly_above_minus_1pct`
- PASS — `vs_context_mean_noninferior_minus_1pct`
- PASS — `vs_context_cluster_95ci_lower_strictly_above_minus_1pct`
- PASS — `generator_calls_reduction_vs_exact_at_least_80pct`
- PASS — `mean_post_bootstrap_switches_at_most_5`

Generator-call reduction vs exact: 82.05%.
Generator-call reduction vs original context: 2.78%.
Switch reduction vs original context: 3.39%.

Even a complete PASS here only licenses freezing the candidate for fresh validation; it is not paper or SOTA evidence.
