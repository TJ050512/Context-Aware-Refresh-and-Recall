# Selective stale-field repair smoke gate

> This is a potential-field mechanism diagnostic, not an OnlineGGO/GPIBT result.

- All repair vs lazy (mechanism headroom): -3.03% (95% CI [-27.44%, 14.17%], p=1.000000)
- Top-25 vs random-25 (selector value): 6.82% (95% CI [-4.79%, 19.14%], p=0.375000)
- Top-25 vs lazy: 18.33% (95% CI [-8.20%, 44.33%], p=0.375000)

- Top-25 gain capture: 0.00%
- Top-25 exposure capture: 52.25%
- Lazy stale-fraction AUC: 0.344
- Top-25 mechanism overhead: 5.21%

## Checks

- FAIL — `all_vs_lazy_gain_at_least_5pct`
- FAIL — `all_vs_lazy_ci_excludes_zero`
- PASS — `top_vs_random_gain_at_least_3pct`
- FAIL — `top_vs_random_ci_excludes_zero`
- FAIL — `top_captures_at_least_70pct_all_gain`
- FAIL — `top_captures_at_least_60pct_exposure`
- PASS — `lazy_stale_auc_at_least_0_30`
- PASS — `map_directions_nonnegative`
- PASS — `mechanism_overhead_below_10pct`
- PASS — `zero_collisions`

Overall: **NO-GO / REVISE**
