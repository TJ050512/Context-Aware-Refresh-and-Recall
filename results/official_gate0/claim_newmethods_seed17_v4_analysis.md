# New-method smoke analysis

- Source: `/Users/maxiaoxiao.27/Documents/DAI/research_workspace/results/official_gate0/claim_newmethods_seed17_v4.json`
- SHA-256: `25d643cb926375dfdd2b9d9b620292753300306d0ca00a4b2f1ac69616c62895`
- Target runs: 18
- Audit: PASS
- Recommendation: **GO_DEV10_SCREEN_ONLY**

The recommendation is an exploratory screen only; it is not paper or SOTA evidence.

## Aggregate

| method | throughput | finished | calls | post pubs | paired vs exact | paired vs bootstrap | W/T/L vs exact |
|---|---:|---:|---:|---:|---:|---:|---:|
| exact_even_B25 | 1.78500 | 1071.0 | 9.00 | 8.00 | +0.00% | -8.12% | 0/3/0 |
| bootstrap_only | 1.94500 | 1167.0 | 1.00 | 0.00 | +9.01% | +0.00% | 3/0/0 |
| js_B25 | 1.92278 | 1153.7 | 9.00 | 8.00 | +7.64% | -1.16% | 3/0/0 |
| js_cap_B25 | 1.96778 | 1180.7 | 5.67 | 4.67 | +10.11% | +1.17% | 3/0/0 |
| causal_block_B25 | 1.75167 | 1051.0 | 9.00 | 8.00 | -1.56% | -9.52% | 1/0/2 |
| proposed_no_cohort_B25 | 1.83333 | 1100.0 | 9.00 | 8.00 | +2.63% | -5.74% | 3/0/0 |

## stationary

| method | throughput | finished | calls | post pubs | paired vs exact | paired vs bootstrap | W/T/L vs exact |
|---|---:|---:|---:|---:|---:|---:|---:|
| exact_even_B25 | 1.65000 | 990.0 | 9.00 | 8.00 | +0.00% | -4.62% | 0/1/0 |
| bootstrap_only | 1.73000 | 1038.0 | 1.00 | 0.00 | +4.85% | +0.00% | 1/0/0 |
| js_B25 | 1.73000 | 1038.0 | 9.00 | 8.00 | +4.85% | +0.00% | 1/0/0 |
| js_cap_B25 | 1.79167 | 1075.0 | 5.00 | 4.00 | +8.59% | +3.56% | 1/0/0 |
| causal_block_B25 | 1.70500 | 1023.0 | 9.00 | 8.00 | +3.33% | -1.45% | 1/0/0 |
| proposed_no_cohort_B25 | 1.66167 | 997.0 | 9.00 | 8.00 | +0.71% | -3.95% | 1/0/0 |

## abrupt

| method | throughput | finished | calls | post pubs | paired vs exact | paired vs bootstrap | W/T/L vs exact |
|---|---:|---:|---:|---:|---:|---:|---:|
| exact_even_B25 | 1.99000 | 1194.0 | 9.00 | 8.00 | +0.00% | -6.57% | 0/1/0 |
| bootstrap_only | 2.13000 | 1278.0 | 1.00 | 0.00 | +7.04% | +0.00% | 1/0/0 |
| js_B25 | 2.15833 | 1295.0 | 9.00 | 8.00 | +8.46% | +1.33% | 1/0/0 |
| js_cap_B25 | 2.23500 | 1341.0 | 6.00 | 5.00 | +12.31% | +4.93% | 1/0/0 |
| causal_block_B25 | 1.86167 | 1117.0 | 9.00 | 8.00 | -6.45% | -12.60% | 0/0/1 |
| proposed_no_cohort_B25 | 2.06500 | 1239.0 | 9.00 | 8.00 | +3.77% | -3.05% | 1/0/0 |

## recurrent

| method | throughput | finished | calls | post pubs | paired vs exact | paired vs bootstrap | W/T/L vs exact |
|---|---:|---:|---:|---:|---:|---:|---:|
| exact_even_B25 | 1.71500 | 1029.0 | 9.00 | 8.00 | +0.00% | -13.16% | 0/1/0 |
| bootstrap_only | 1.97500 | 1185.0 | 1.00 | 0.00 | +15.16% | +0.00% | 1/0/0 |
| js_B25 | 1.88000 | 1128.0 | 9.00 | 8.00 | +9.62% | -4.81% | 1/0/0 |
| js_cap_B25 | 1.87667 | 1126.0 | 6.00 | 5.00 | +9.43% | -4.98% | 1/0/0 |
| causal_block_B25 | 1.68833 | 1013.0 | 9.00 | 8.00 | -1.55% | -14.51% | 0/0/1 |
| proposed_no_cohort_B25 | 1.77333 | 1064.0 | 9.00 | 8.00 | +3.40% | -10.21% | 1/0/0 |

## Invariant and screening gates

- Pairing/budget/safety/attribution audit failures: 0
- Planner timeouts: 0
- Unexposed zero-route completions: 0
- Route reasons: `{"inherited_goal_route": 12, "init_pp": 72, "task_change": 33513}`
- inherited_goal_route observed: True
- causal_block signal screen: False
- js_cap signal screen: True

