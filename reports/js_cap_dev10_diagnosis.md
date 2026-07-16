# `js_cap_B25` dev10 diagnosis (development evidence only)

Artifact: `results/official_gate0/claim_js_cap_dev10_v4.json`

- Artifact SHA-256: `bb2e4c2905a50976bbf1523b06c412086c4ede47eac6eb88343d16b30f81e427`
- Simulator SHA-256: `9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5`
- Design: 10 paired development seeds (17--26), 3 workloads, 30 scored windows, 400 agents.
- This is diagnostic development evidence, not locked-test evidence and not a global LMAPF SOTA result.

## Main result

| Workload | bootstrap | js_cap | Paired difference (cap - bootstrap) | 95% paired t interval | Wins / 10 |
|---|---:|---:|---:|---:|---:|
| stationary | 952.6 | 962.3 | +9.7 | [-35.2, +54.6] | 5 |
| abrupt | 1252.7 | 1232.0 | -20.7 | [-82.2, +40.8] | 5 |
| recurrent | 1253.9 | 1222.7 | -31.2 | [-115.6, +53.2] | 3 |
| all 30 pairs | 1153.07 | 1139.00 | -14.07 | [-47.8, +19.6] | 13 / 30 |

`js_cap_B25` uses 5.03 post-bootstrap publications on average, versus zero for bootstrap-only. It is therefore Pareto-dominated by bootstrap-only in this development sample, although the paired difference is noisy and its interval includes zero. It does improve over `js_B25` (+21.1 tasks/run) and `exact_even_B25` (+24.0 tasks/run), showing that abstention helps but does not yet abstain enough.

## Where the -422-task aggregate gap appears

Windows 0--4 are exactly identical for all 30 pairs. The first `js_cap` publication occurs at decision 5 in 29/30 pairs and at 6 in the remaining pair. Thus divergence starts only after a publication, as expected.

Across all 30 pairs, the net gap is -422 tasks. Negative-window mass is -854 and positive-window mass is +432. The largest aggregate negative windows are:

| Decision window | Aggregate task difference |
|---:|---:|
| 20 | -113 |
| 8 | -93 |
| 13 | -93 |
| 14 | -83 |
| 21 | -83 |
| 12 | -70 |
| 18 | -59 |
| 24 | -56 |

There is a late recovery (+82 at window 25, +63 at 27, +134 at 28, +107 at 29), but it does not erase the middle-horizon deficit. The top five negative windows alone sum to -465.

By workload, the cumulative trajectory is qualitatively different:

- stationary bottoms near -18 tasks around window 16 and recovers to +9.7 by the end;
- abrupt is near parity through window 13, then falls to -28.4 by window 26 and recovers to -20.7;
- recurrent loses throughout the middle horizon, reaches -47.9 at window 24, and recovers to -31.2.

The loss is concentrated in a few high-variance pairs. The five worst are recurrent/20 (-216), abrupt/21 (-171), recurrent/19 (-135), recurrent/23 (-128), and stationary/21 (-120). They contribute -770 of the -1276 negative-pair mass. Positive pairs contribute +854, hence the net -422.

## Publication-timing diagnosis

The controller almost deterministically makes its first optional publication at the first eligible opportunity. At that first publication, the mean score-minus-75%-quantile margin is only 0.011; over all 151 publications the median margin is 0.0061, and 108/151 margins are at most 0.01. The trigger is therefore often normal monotone accumulation of active-goal JS after a reset, not a clearly exceptional workload event.

The manifest can be used for retrospective diagnosis only (it is forbidden to the controller). Abrupt and recurrent phase changes occur at scored offsets 150, 300, and 450, i.e. between decision windows 7/8, at 15, and between 22/23. The nearly universal first publication at decision 5 therefore occurs about 50 scored steps before the first real distribution change. It is a premature update to another estimate of the same initial regime.

The current release-only JS is not yet a reliable fix by itself. Its stationary-workload mean has large recurring peaks at decisions 3 (0.232), 9 (0.358), 14 (0.374), 20 (0.353), and 25 (0.370), comparable to the dynamic workloads. This is consistent with finite-sample/arrival-cadence aliasing (`release_interval=110` versus a 20-step decision window), not true regime change. A raw threshold such as release-JS >= 0.1 would therefore false-alarm on stationary data. A replacement should aggregate a fixed number of released tasks, use Dirichlet/shrinkage correction, and apply a sequential two-sample change test or confidence sequence with an explicit false-alarm target.

Descriptively assigning each interval to the publication that starts it gives:

| Publication ordinal | Number | Mean decision | Mean interval difference vs bootstrap |
|---:|---:|---:|---:|
| 1 | 30 | 5.0 | -3.87 |
| 2 | 30 | 11.4 | -10.07 |
| 3 | 30 | 17.4 | -5.50 |
| 4 | 29 | 21.8 | -0.41 |
| 5 | 19 | 23.7 | +7.89 |
| 6 | 9 | 24.9 | -6.78 |

This interval attribution is descriptive, not a marginal causal effect: later intervals carry effects of all earlier publications and their states have already diverged from bootstrap.

The strongest mechanistic problem is version exposure. After a publication, the mean active-route fraction for the new guidance is only 0.10 after one window, 0.19 after two, 0.26 after three, 0.31 after four, and does not reach about 0.5 until roughly eight windows. Nevertheless the current minimum gap permits another publication after two windows. Of the 121 publications after the first, 102 occur with current-version active-route fraction below 0.5. Their following intervals average -4.60 tasks relative to bootstrap, versus +8.58 for the 19 events at or above 0.5. This association is endogenous but directly motivates a maturity/dwell guard experiment.

The existing `current_version_maturity` feature cannot provide that guard: it is the maximum of route fraction and build-count maturity, and build-count maturity reaches 1 rapidly. `current_cohort_service_degradation` is also non-informative here: it is exactly zero in every `js_cap`, `js_B25`, and `exact_even_B25` window.

## Seed trajectories and why naive rollback is unsafe

The sign frequently reverses late. Examples include recurrent/21 (-19 in windows 5--14, then +209 afterward, final +190), recurrent/18 (-27 in windows 5--14, final +98), and abrupt/18 (cumulative -45 through window 24, then +89 in the final five windows, final +44). Conversely abrupt/21 is +6 in windows 5--9 but ends -171, and recurrent/19 is +5 in windows 5--14 but ends -135.

Even with the unavailable bootstrap counterfactual, the sign of the first four post-publication windows predicts the final sign in only 14/30 pairs. Six windows improves this to 22/30, but would still incorrectly roll back delayed winners such as recurrent/18 and recurrent/21. A rule based only on a short before/after throughput dip is therefore not causally safe.

## Online-only selective abstention analysis

No currently logged scalar feature robustly separates beneficial from harmful first publications. Absolute correlations with final paired outcome are weak: active-route fraction is strongest at -0.28; goal JS is -0.03; release-only JS is -0.04; throughput drop is +0.04; wait ratio is +0.06. Current cohort degradation is constant zero.

Two development hypotheses are worth testing, but neither is established:

1. **Need gate:** publish only when the pre-trigger five-window mean reward is at most about 31.7 completions/window (normalized: 0.07925 completions/agent/window). This simple threshold selects 16/30 pairs and has an in-sample oracle-policy gain of +351 tasks total; grouped leave-one-seed-out tuning gives +216 total. However seed 23 alone loses -199 under the cross-validated rule, so this is not safe or validation-ready.
2. **Exposure gate:** at the first trigger, active-route fraction at most about 0.487 is associated with gain (+431 total in 9 selected pairs; grouped leave-one-seed-out +142). This is statistically fragile, dominated by a few large winners, and is conceptually different from the post-publication maturity guard. It should be treated only as a screening ablation.

Across the existing feature stumps, most leave-one-seed-out results are negative. Thus there is no defensible evidence yet for a purely observational one-scalar abstention rule.

## Recommended next controller

The lowest-risk next experiment is a **need-triggered, exposure-gated, reversible controller**:

1. Use an online need gate based on normalized rolling reward level/deterioration; do not publish on active-goal JS alone.
2. Require a statistically calibrated exogenous change signal from released-goal events, not active-task composition alone and not the current raw windowed release JS. Active goals are affected by the current guidance and can create a feedback trigger; raw released-goal JS has strong stationary false alarms.
3. After any publication, embargo further publications until both `guidance_age_windows >= 6` (preferably screen 6 and 8) and `current_version_route_fraction >= 0.5`. Do not use the existing max-combined maturity variable for this gate.
4. Cache the previous guidance. Count generator calls and deployed revisions separately. A rollback reinstalls cached guidance without claiming a new generator call.
5. Do not rollback on raw pre/post reward. First require route exposure and an anytime-valid harm test against a concurrent control. The cleanest design is a randomized canary/control rollout (agent or spatial clusters) with matched release time, source/goal bin, and route-exposure maturity. Multi-agent interference must be acknowledged; cluster randomization is preferable to pretending tasks are independent.
6. If canary support is too large a simulator change, first run the simpler maturity/need gates against bootstrap. This can show whether reducing 5.03 calls toward 1--2 preserves the stationary gain without the abrupt/recurrent losses, but it cannot support a causal rollback claim.

Suggested dev ablations (do not touch locked seeds):

- cap + minimum dwell 6;
- cap + minimum dwell 8;
- cap + active-route fraction >= 0.5;
- cap + dwell 6 + fraction >= 0.5;
- preceding gate + normalized five-window reward need threshold;
- preceding gate + a fixed-count, shrinkage-calibrated release change detector;
- bootstrap-only and current `js_cap_B25` as mandatory controls.

The acceptance screen should require paired improvement over bootstrap-only, fewer calls than exact-B25, and no workload with a large negative confidence bound. Tune only on development seeds, freeze the rule, then run validation.

## Oracle ceilings (diagnostic only; not deployable methods)

These use future rewards and therefore must never be reported as controller performance:

| Oracle | Mean tasks/run | Gain over bootstrap |
|---|---:|---:|
| Per-run choose better of bootstrap and js_cap | 1181.53 | +28.47 |
| Per-run choose best of all four logged arms | 1192.57 | +39.50 |
| Per-window choose better of bootstrap and js_cap | 1242.50 | +89.43 |
| Per-window choose best of all four logged arms | 1289.87 | +136.80 |

The per-window values splice mutually incompatible state trajectories and are only loose descriptive upper ceilings. The realistic opportunity indicated by the per-run binary oracle is about +28.5 tasks/run if a causal selector could identify when to abstain, but the current online features do not yet identify that selector reliably.
