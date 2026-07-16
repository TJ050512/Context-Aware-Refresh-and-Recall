# Selective stale-field repair smoke gate

> This is a potential-field mechanism diagnostic, not an OnlineGGO/GPIBT result.

- All repair vs lazy (mechanism headroom): -11.14% (95% CI [-28.19%, 14.53%], p=0.415039)
- Top-25 vs random-25 (selector value): -7.17% (95% CI [-12.59%, -1.18%], p=0.039551)
- Top-25 vs lazy: 0.07% (95% CI [-13.18%, 17.85%], p=0.994629)

- Top-25 gain capture: 0.00%
- Top-25 exposure capture: 55.38%
- Lazy stale-fraction AUC: 0.289
- Top-25 mechanism overhead: 2.96%

## Checks

- FAIL — `all_vs_lazy_gain_at_least_5pct`
- FAIL — `all_vs_lazy_ci_excludes_zero`
- FAIL — `top_vs_random_gain_at_least_3pct`
- FAIL — `top_vs_random_ci_excludes_zero`
- FAIL — `top_captures_at_least_70pct_all_gain`
- FAIL — `top_captures_at_least_60pct_exposure`
- FAIL — `lazy_stale_auc_at_least_0_30`
- FAIL — `map_directions_nonnegative`
- PASS — `mechanism_overhead_below_10pct`
- PASS — `zero_collisions`

Overall: **NO-GO / REVISE**
