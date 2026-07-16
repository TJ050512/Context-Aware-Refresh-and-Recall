# Locked smoke-validation assessment

> This is local mechanism evidence, not an Online GGO or public-benchmark result.

## Paired effects

- BETG-25 vs periodic-20 (primary): 6.35% (95% CI [2.74%, 10.43%], p=0.005859)
- BETG-25 vs drift-25: 1.14% (95% CI [-3.10%, 5.47%], p=0.612793)
- BETG-10 vs periodic-50: 0.06% (95% CI [-3.01%, 2.76%], p=0.958984)
- Static BETG-25 vs periodic-20: 1.73% (95% CI [-0.02%, 3.59%], p=0.103516)
- Open-map BETG-25 vs periodic-20: 2.13% (95% CI [1.35%, 3.08%], p=0.000488)
- 16-agent BETG-25 vs periodic-20: 0.40% (95% CI [-0.24%, 1.13%], p=0.313477)
- Three-corridor BETG-25 vs periodic-20: 1.34% (95% CI [-1.73%, 4.73%], p=0.455078)

## Cost and safety

- Throughput fraction of always-refresh: 65.86%
- Runtime fraction of always-refresh: 44.17%
- Refresh rate: 24.57%
- Controller overhead: 3.14%
- Budget violation rate: 0.00%
- Collisions: 0
- Proposed-method deadlock rate: 0.00%
- All-method deadlock rate: 0.36%

## Registered checks

- PASS — `primary_gain_at_least_5pct`
- PASS — `primary_ci_excludes_zero`
- FAIL — `beats_simple_drift_trigger_significantly`
- PASS — `three_corridor_direction_positive`
- PASS — `static_degradation_within_2pct`
- PASS — `open_degradation_within_2pct`
- PASS — `n16_degradation_within_2pct`
- FAIL — `at_least_95pct_always_refresh_throughput`
- PASS — `at_least_20pct_faster_than_always_refresh`
- PASS — `refresh_rate_at_most_25pct`
- PASS — `controller_overhead_below_5pct`
- PASS — `budget_violation_at_most_5pct`
- PASS — `zero_collisions`
- PASS — `zero_proposed_deadlocks`

Overall: **NOT YET PASS**
