# Local mechanism smoke-pilot report

> Diagnostic two/three-corridor results only. These are not Online GGO, public-map, or SOTA results.

## Primary paired comparison

- Proposed: `betg_25`
- Baseline: `periodic_20`
- Paired seeds: 3
- Mean relative throughput gain: -0.00%
- Paired bootstrap 95% CI: [-25.15%, 19.37%]
- Exact/Monte-Carlo sign-flip p-value: 1.000000

## Overall method means

| Method | Throughput | Wait rate | Refresh rate | Wall time (s) |
|---|---:|---:|---:|---:|
| always_refresh | 0.5822 | 0.0736 | 1.0000 | 0.1554 |
| always_reuse | 0.2498 | 0.1814 | 0.0000 | 0.0283 |
| betg_10 | 0.2827 | 0.1495 | 0.0667 | 0.0745 |
| betg_25 | 0.3284 | 0.1395 | 0.0756 | 0.0771 |
| drift_10 | 0.3302 | 0.1390 | 0.1178 | 0.0458 |
| drift_25 | 0.3813 | 0.1108 | 0.2511 | 0.0624 |
| periodic_20 | 0.3440 | 0.0953 | 0.2600 | 0.0631 |
| periodic_50 | 0.3551 | 0.1438 | 0.1000 | 0.0441 |
| shortest | 0.2498 | 0.1814 | 0.0000 | 0.0201 |

## Interpretation gate

NO-GO on the current controller/configuration: do not claim value. Diagnose the action trace and improve the mechanism before large public runs.
