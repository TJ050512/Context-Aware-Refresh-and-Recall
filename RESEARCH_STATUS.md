# Research status and decision log

Last updated: 2026-07-15

## Completed

- Built a collision-checked deterministic LMAPF smoke backend and fixed task
  tapes.
- Implemented periodic, drift-threshold, and budgeted sliding-window controls.
- Added an official OnlineGGO environment adapter with RDLU validation,
  defensive caching, guidance hashes/versions, separate timings, and faulted
  run semantics.
- Pinned OnlineGGO at commit
  `ff6d830e2fd5bf85ccbb72eaec0fb8df1cf1c256` and audited its update semantics.
- Added strict, non-overlapping task/planner traces, external versus
  normalized-weight hashes, actual guide-path construction events, and a
  route-cohort outcome tracker.
- Current dependency-free suite: 38 tests, all passing.

### Official Linux Gate 0 bring-up — passed on 2026-07-13

- Configured Ubuntu 20.04 / x86_64 / Python 3.9.25 on AutoDL and compiled the
  pinned official OnlineGGO/GPIBT `period_on_sim` extension with the frozen
  Gate 0 flags. The archived binary SHA-256 is
  `2f3ff2946e74c307bc667dffbf9a8f47fa37f2bc16ddf38b11cca14e5e0c2c83`.
- Fixed ignored `reset(seed)`, unseeded planner priority shuffling, random
  comparator tie breaks, an uninitialized heap comparator, and coupled
  start/task/distribution RNG streams. Effective seed bundles, starts,
  initial planner order, distribution states, task events, paths, and route
  builds are now in the trace.
- The official Python 3.9 suite passes 38/38 tests. Preflight reports zero
  blockers and `ready_to_build=true`, `ready_to_run=true`.
- Two independent 400-agent, 20-step runs at seed 17 match exactly after
  excluding only steady-clock seconds; their causal replay payload SHA-256 is
  `4d8a6adc3761f1bbf1a3dce21620f046bfe903c6a5e8749ed016fb092d6faa51`.
- Two independent 400-agent, 200-step runs also match exactly, including every
  per-agent action; replay payload SHA-256 is
  `27375fc041b59e794cc18d330dfdc61e7534b3c81df6c41e657ba1d62a884d6f`.
- A seed-17 versus seed-18 control changes every audited causal component
  (seed bundle, starts, planner order, distribution tape, task tape, paths),
  confirming that the repair did not collapse different scenarios together.

These are correctness and reproducibility results, not method-effect or SOTA
evidence.

Across the eager-refresh diagnostic, development sweep, and locked
selective-repair validation, 3,336 local runs have been completed. Only the
last 528 runs used untouched locked seeds; none of these local runs is claimed
as an official OnlineGGO/GPIBT benchmark.

## Experiment decisions

### Eager refresh smoke — diagnostic only

The first 1,944-run locked smoke validation found BETG-25 versus periodic-20
`+6.35%` throughput (CI `[+2.74%, +10.43%]`, p=`0.005859`). It failed two
substantive gates: only `65.86%` of always-refresh throughput and no significant
advantage over the simple drift trigger. Source audit later showed that this
smoke backend's eager global refresh does not match official GPIBT semantics.
It is not paper evidence.

### Selective stale-field repair — No-Go

After a development sweep of 864 runs, `scale=2`, delay `0` was frozen and
tested on 12 new seeds, two maps, and abrupt/recurrent shifts (528 runs).

- Lazy future-only update vs no update, total throughput: `+13.79%`, CI
  `[+7.75%, +20.32%]`, p=`0.000488`.
- All repair vs lazy, total throughput: `-10.59%`, CI
  `[-14.83%, -5.98%]`, p=`0.003418`.
- Top-25 vs random-25, first-100-step throughput: `+4.66%`, CI
  `[-4.82%, +15.53%]`, p=`0.433594`.
- Top-25 vs lazy, total throughput: `-0.29%`, CI
  `[-5.05%, +4.72%]`, p=`0.914551`.
- Collisions: `0`.

Conclusion: guidance updates are useful in this diagnostic, but retroactively
repairing active artifacts is harmful on average and the exposure selector is
not established. Do not write a selective-repair paper from these results.

## Current direction

The surviving hypothesis is route-cohort-aware event-triggered **guidance
publication**: decide when a new graph should govern subsequently constructed
guide paths while preserving in-flight paths. Route cohorts are defined by the
graph actually used at guide-path construction, not by task assignment time.
This matches the official source and does not rely on a false global-replanning
cost story. See `GUIDANCE_VERSIONING_EXPERIMENT.md`.

## Mechanism MVP — conditional Go for the publication question

On 2026-07-13, the official compiled 400-agent GPIBT backend was used for a
600-step dynamic Gaussian-demand MVP (seed 17, 20-step decision windows,
distribution shifts every 160 steps).  This was a method experiment, not a
reproduction run.  The tested next-route-flow generator did not establish
positive publication headroom:

- bootstrap once and reuse: `1606` completed tasks;
- publish at every observed distribution shift: `1583`;
- fixed period 100: `1562` after correcting stale distribution state;
- publish after a 40-step route-cohort delay: `1502` after the same correction.

The delayed condition initially exposed a state-caching bug: a generator that
was not invoked at the shift missed the transient distribution-update record
and later generated from stale weights.  The runner now observes exogenous
distribution state every window, independently of publication.  Correcting
the bug made the delayed result worse rather than reversing it.

A frozen strength sweep (`flow_bias` in `0.01, 0.025, 0.05, 0.075, 0.10,
0.15`) also failed to make shift-time publication beat bootstrap reuse on the
development seed.  Therefore controller or trigger tuning is suspended for
this generator.  These runs reject the temporary hand-written guidance
heuristic; they do **not** yet reject publication control with a trained
OnlineGGO checkpoint.

The frozen-phase and dynamic subset diagnostics were completed on three
development seeds.  Causal phase-static guidance beat uniform in 6/9
seed-phase pairs, with mean paired relative gain `+4.00%`.  In the dynamic
600-step setting, the per-seed hindsight publication subset beat bootstrap
reuse on all three seeds by `+18`, `+21`, and `+37` tasks (mean `+1.71%`),
whereas publishing at all three shifts had mean paired gain exactly zero.

Conclusion: the paper question receives a **conditional Go**.  Refresh value
changes sign across workload shifts, and selective-publication headroom exists
on the official backend.  The current hand-written trigger is still a No-Go;
the next gate is a causal trigger frozen on development data and evaluated on
untouched seeds.  See `MVP_DIRECTION_DECISION.md` for exact tables, scope, and
the claim boundary.

## Current blockers before claim-bearing Gate 0B

- The checkout does not contain the trained OnlineGGO generator checkpoint;
  obtain one or run fresh CMA-ES training before calling any schedule result an
  OnlineGGO comparison.
- Same-method replay now passes, but cross-method causal pairing still needs an
  explicitly exogenous per-agent task/release tape rather than relying only on
  identical episode seeds.
- Complete the asymmetric known-cell RDLU sentinel and the publication-boundary
  route-build sentinel under the compiled extension.
- Then run the locked 10-seed Gate 0B matrix: never, always, periods 20/50/100,
  and oracle shift-time publication on one public dynamic warehouse setting.

## Same-call Experiment B — complete on 2026-07-15

The fresh-root, high-power Experiment B is complete: 8 methods x 40 root
clusters x 3 workloads x 4 scenarios = 3,840 runs. The effect-blind integrity
audit passed before the frozen analyzer was executed. All runs completed with
zero failures, unfinished attempts, retries, timeouts, or selective deletions.

The registered 1% non-inferiority claim versus 26-call dense refresh failed all
three gates: mean effect -0.8006%, 95% root CI [-1.1935%, -0.3966%], shifted
exact p=0.1693. This prohibits dense-equivalence, near-lossless, and within-1%
claims.

The resource-aware result is positive and paper-usable. CARR averages 5.458
generator calls, 79.006% fewer than dense B25, is non-dominated on the
empirical mean tasks--calls frontier, and significantly outperforms all five
frozen low-call comparators after Holm correction. Historical
reactivation does not improve throughput versus the no-reactivation ablation;
its supported role is call substitution.

Decision: write a paired Pareto/resource-allocation DAI paper, not a global
SOTA or dense-equivalence paper. Use Experiment B as standalone primary
evidence; disclose but do not pool A2. See
`reports/SAME_CALL_B_DECISION_2026-07-15.md` for exact results and claim limits.
