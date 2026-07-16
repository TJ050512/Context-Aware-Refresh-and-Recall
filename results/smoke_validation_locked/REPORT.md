# Local mechanism smoke-pilot report

> Diagnostic two/three-corridor results only. These are not Online GGO, public-map, or SOTA results.

## Primary paired comparison

- Proposed: `betg_25`
- Baseline: `periodic_20`
- Paired seeds: 12
- Mean relative throughput gain: 6.35%
- Paired bootstrap 95% CI: [2.74%, 10.43%]
- Exact/Monte-Carlo sign-flip p-value: 0.005859

## Overall method means

| Method | Throughput | Wait rate | Refresh rate | Wall time (s) |
|---|---:|---:|---:|---:|
| always_refresh | 0.7268 | 0.0419 | 1.0000 | 0.3982 |
| always_reuse | 0.5448 | 0.1224 | 0.0083 | 0.0766 |
| betg_10 | 0.5608 | 0.0980 | 0.0988 | 0.1362 |
| betg_25 | 0.6077 | 0.0729 | 0.2358 | 0.1810 |
| drift_10 | 0.5666 | 0.0991 | 0.0966 | 0.1242 |
| drift_25 | 0.5995 | 0.0787 | 0.2185 | 0.1653 |
| periodic_20 | 0.5956 | 0.0725 | 0.2500 | 0.1750 |
| periodic_50 | 0.5569 | 0.0987 | 0.1000 | 0.1264 |
| shortest | 0.5448 | 0.1224 | 0.0000 | 0.0459 |

## Interpretation gate

GO for official-backbone replication: the local mechanism cleared the registered 5% paired throughput gate. This still is not a paper result.
