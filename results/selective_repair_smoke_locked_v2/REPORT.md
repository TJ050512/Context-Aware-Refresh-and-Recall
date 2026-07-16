# Selective stale-field repair smoke gate

> This is a potential-field mechanism diagnostic, not an OnlineGGO/GPIBT result.

- All repair vs lazy (mechanism headroom): -13.11% (95% CI [-21.46%, -3.99%], p=0.018066)
- Top-25 vs random-25 (selector value): 4.66% (95% CI [-4.82%, 15.53%], p=0.433594)
- Top-25 vs lazy: 3.41% (95% CI [-7.42%, 14.31%], p=0.566895)
- Lazy update vs no update (generator validity): 15.12% (95% CI [1.65%, 28.73%], p=0.061523)
- Lazy update vs no update (total throughput): 13.79% (95% CI [7.75%, 20.32%], p=0.000488)
- All repair vs lazy (total throughput): -10.59% (95% CI [-14.83%, -5.98%], p=0.003418)
- Top-25 vs lazy (total throughput): -0.29% (95% CI [-5.05%, 4.72%], p=0.914551)

- Top-25 gain capture: 0.00%
- Top-25 exposure capture: 38.72%
- Lazy stale-fraction AUC: 0.366
- Top-25 mechanism overhead: 4.13%

## Checks

- FAIL — `all_vs_lazy_gain_at_least_5pct`
- FAIL — `all_vs_lazy_ci_excludes_zero`
- PASS — `top_vs_random_gain_at_least_3pct`
- FAIL — `top_vs_random_ci_excludes_zero`
- PASS — `updated_guidance_beats_no_update`
- PASS — `updated_guidance_total_ci_excludes_zero`
- FAIL — `top_total_gain_at_least_3pct`
- FAIL — `top_captures_at_least_70pct_all_gain`
- FAIL — `top_captures_at_least_60pct_exposure`
- PASS — `lazy_stale_auc_at_least_0_30`
- PASS — `map_directions_nonnegative`
- PASS — `mechanism_overhead_below_10pct`
- PASS — `zero_collisions`

Overall: **NO-GO / REVISE**
