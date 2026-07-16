# MVP direction decision: conditional GO

Date: 2026-07-14

## Decision

**Continue the route-cohort-aware, event-triggered guidance-publication
direction.**  The MVP establishes both ingredients needed to justify further
research:

1. workload phases have different guidance quality; and
2. selective publication has positive hindsight headroom on the real dynamic
   official GPIBT trajectory, while publishing every shift does not.

This is a mechanism-level **conditional GO**, not a deployable-method result
and not a SOTA claim.  The current delayed-cohort trigger remains a No-Go.

## Frozen-phase guidance-quality diagnostic

Configuration: official compiled GPIBT, warehouse-small-narrow Kiva map, 400
agents, 100-step warmup, 200-step frozen evaluation, decision window 20,
three seeds and three exogenous workload phases.  `phase_static` uses only the
frozen distribution and warmup state.

| Seed | Phase | Uniform | Phase-static | Delta |
|---:|---:|---:|---:|---:|
| 17 | 0 | 763 | 776 | +13 |
| 17 | 1 | 247 | 240 | -7 |
| 17 | 2 | 283 | 297 | +14 |
| 18 | 0 | 735 | 858 | +123 |
| 18 | 1 | 219 | 218 | -1 |
| 18 | 2 | 198 | 205 | +7 |
| 19 | 0 | 709 | 693 | -16 |
| 19 | 1 | 247 | 264 | +17 |
| 19 | 2 | 220 | 237 | +17 |

Phase-static improves 6/9 paired conditions.  The unweighted mean paired
gain is `+18.56` tasks and the mean paired relative gain is `+4.00%`.
Variance is high, which is itself evidence that blindly publishing every new
graph is unsafe.

## Dynamic publication-subset diagnostic

Configuration: official compiled GPIBT, the same map and 400 agents, 40-step
warmup, 600-step dynamic evaluation, shifts at timesteps 160/320/480, decision
window 20.  A three-bit mask is a hindsight diagnostic indicating at which
observed shifts the new graph is published.  Every condition bootstraps the
same initial graph once.

| Seed | Reuse after bootstrap | Best mask | Best tasks | Gain | Publish all |
|---:|---:|:---:|---:|---:|---:|
| 17 | 1606 | `011` | 1624 | +18 (+1.12%) | 1583 (-23) |
| 18 | 1409 | `100` | 1430 | +21 (+1.49%) | 1405 (-4) |
| 19 | 1463 | `110` | 1500 | +37 (+2.53%) | 1490 (+27) |

The per-seed hindsight schedule improves all 3/3 seeds, with mean gain
`+25.33` tasks or `+1.71%`.  Publishing all three shifts has mean paired gain
exactly `0` tasks.  The best common mask on these development seeds is `100`
with mean `+12.33` tasks, but it improves only 2/3 seeds and was selected on
the same data, so it is not evidence for a deployable fixed policy.

## What is established

- The guidance channel materially changes throughput; this is not a no-op or
  hashing/versioning artifact.
- Some workload-specific graphs beat uniform/static reuse.
- Refresh value changes sign across shifts and seeds.
- A selective schedule can beat reuse on every tested seed in hindsight.
- Always publishing is not a sufficient policy.

## What is not established

- No causal trigger has yet predicted the hindsight masks on held-out seeds.
- Three development seeds are insufficient for a paper claim or significance
  test.
- The hand-written next-route-flow generator is not OnlineGGO and must not be
  called SOTA.
- Cross-method task assignment is still treatment-dependent; a fully
  exogenous task/release tape is required for the final claim-bearing suite.
- Only one map, one density, abrupt Gaussian shifts, and short horizons have
  been tested.

## Next claim-bearing gate

1. Use development seeds to label each shift with the paired marginal value of
   publication, without tuning on test seeds.
2. Fit a small causal trigger from pre-publication features: goal-distribution
   drift, edge-flow drift, throughput drop, wait rate, route-build rate,
   guidance age, and predicted graph drift.
3. Freeze the trigger and compare it on at least ten untouched seeds against
   bootstrap reuse, always publish, periods 20/50/100/200, JS-threshold,
   throughput-drop threshold, and a hindsight subset oracle.
4. Repeat with an official trained OnlineGGO checkpoint and at least one second
   public map before making a general or SOTA claim.

## Archived evidence

Artifacts and the exact compiled simulator are in
`results/official_gate0/mvp_direction/`.  The phase-enabled simulator SHA-256
is `03e5def60875cb80195297ec51297639c299b8db587ccba4c5b2d0ff2a820f94`.
