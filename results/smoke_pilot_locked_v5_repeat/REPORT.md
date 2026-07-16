# Local mechanism smoke-pilot report

> Diagnostic two/three-corridor results only. These are not Online GGO, public-map, or SOTA results.

## Primary paired comparison

- Proposed: `betg_25`
- Baseline: `periodic_20`
- Paired seeds: 3
- Mean relative throughput gain: 5.99%
- Paired bootstrap 95% CI: [0.00%, 13.11%]
- Exact/Monte-Carlo sign-flip p-value: 0.500000

## Overall method means

| Method | Throughput | Wait rate | Refresh rate | Wall time (s) |
|---|---:|---:|---:|---:|
| always_refresh | 0.5822 | 0.0736 | 1.0000 | 0.1551 |
| always_reuse | 0.2498 | 0.1814 | 0.0200 | 0.0302 |
| betg_10 | 0.3564 | 0.1442 | 0.1000 | 0.0479 |
| betg_25 | 0.3804 | 0.1009 | 0.2556 | 0.0662 |
| drift_10 | 0.2804 | 0.1541 | 0.0978 | 0.0414 |
| drift_25 | 0.3924 | 0.1130 | 0.2489 | 0.0616 |
| periodic_20 | 0.3440 | 0.0953 | 0.2600 | 0.0631 |
| periodic_50 | 0.3551 | 0.1438 | 0.1000 | 0.0436 |
| shortest | 0.2498 | 0.1814 | 0.0000 | 0.0198 |

## Interpretation gate

BORDERLINE: expand locked smoke seeds once without changing parameters, then decide whether official-backbone integration is worth the cost.
