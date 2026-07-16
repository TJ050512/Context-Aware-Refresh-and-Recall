# What can be written while official experiments run

Date: 2026-07-13

## Safe to draft now

1. **Introduction.** Non-stationary LMAPF needs online traffic guidance, while
   a fixed publication interval cannot distinguish genuine distribution shifts
   from transient congestion.
2. **System semantics.** In the pinned OnlineGGO/GPIBT implementation, changing
   edge weights does not globally rebuild guide paths. The installed graph is
   consumed when a guide path is later constructed.
3. **Problem formulation.** At each eligible window, choose `reuse` or
   `publish`; optimize paired episode throughput/recovery subject to a
   publication-rate or operational-cost guard.
4. **Route cohorts.** Define a route cohort by the normalized graph used at
   actual guide-path construction. Treat cohort service statistics as delayed
   controller feedback and diagnostics, not as unadjusted causal estimates.
5. **Protocol.** Describe Gate 0A semantic/replay sentinels, Gate 0B schedule
   headroom, public-map expansion, paired seeds, locked test manifests, safety
   checks, and paired uncertainty estimates.
6. **Negative pilot.** If space permits, put the local potential-field result
   in an appendix explicitly labeled synthetic/oracle: it rejected selective
   retroactive repair and determined the subsequent research direction.

## Keep as placeholders

- claimed contribution count and wording;
- main quantitative results and any "state of the art" language;
- which learned controller, if any, survives validation;
- final baseline list, maps, densities, runtime budget, and checkpoint;
- effect sizes on official OnlineGGO/GPIBT;
- route-cohort feedback ablations.

## Do not claim from current evidence

- that the local `+13.79%` is an OnlineGGO or public-map result;
- that selective repair improves performance—the locked total effect was
  negative;
- significant post-shift recovery (`p=0.0615` in the local diagnostic);
- that assignment-time cohorts identify route treatment;
- broad LMAPF SOTA before official public-map, equal-budget comparisons.

## Planned result tables

1. **Gate 0 semantics:** build hash, flags, RDLU sentinel, replay hash, trace
   integrity, safety.
2. **Schedule headroom:** never/always/fixed periods/oracle on one warehouse
   development configuration.
3. **Main dynamic suite:** best fixed schedule, simple drift threshold,
   change-point trigger, proposed route-cohort controller.
4. **Efficiency and safety:** publications, generator/planner/end-to-end time,
   collisions, edge swaps, budget violations.
5. **Ablations:** no cohort maturity, no hysteresis, no change features, no
   publication guard.

Use `SUBMISSION_DRAFT.md` for the current registration title/abstract and
`GUIDANCE_VERSIONING_EXPERIMENT.md` for the claim-bearing method protocol.
