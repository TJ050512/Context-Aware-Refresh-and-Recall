# Revised experiment: selective propagation of changed guidance

Date: 2026-07-13

## Status: No-Go after locked smoke validation

This proposal is retained as a negative-result audit trail. After an 864-run
development sweep, the frozen setting was evaluated in 528 runs on 12 new
seeds. All-artifact repair significantly reduced total throughput, and Top-25
did not significantly beat random repair or improve total throughput. See
`results/selective_repair_smoke_locked_v2/REPORT.md`. The current direction is
`GUIDANCE_VERSIONING_EXPERIMENT.md`; do not use the selective-repair framing in
the submission registration.

## Working title

**When Guidance Changes: Budgeted Selective Guide-Path Repair for
Non-Stationary Lifelong MAPF**

## Why the method changed

The official GPIBT source audit shows that updating `map_weights` changes only
future guide-path A* calls. Active agents keep paths built under older guidance.
The earlier local smoke simulator modeled an eager global cache rebuild, so its
results are diagnostic only and cannot validate the official mechanism.

The revised question is:

> After traffic guidance changes, which active agents should receive the new
> guidance immediately when only a bounded number of guide paths can be
> repaired?

This gives a real compute budget—extra weighted A* calls and their measured CPU
time—and addresses an identifiable propagation lag in the public backbone.

## Method under test

At a detected guidance-change event:

1. A frozen generator produces and atomically installs new edge weights.
2. For each eligible active agent, scan its remaining cached guide path and
   compute a cheap positive-exposure score:

   `exposure_i = mean(max(0, w_new(e) - w_old(e)) for e in P_i_remaining)`.

3. Select at most `B` agents with the highest exposure. Initial budgets are
   `B/N ∈ {0.05, 0.10, 0.20}`.
4. Remove all selected paths from the shared flow counts, then regenerate them
   under the new weights in descending exposure order.
5. Record exact A* calls and repair wall time. A diagnostic oracle also repairs
   every eligible agent.

The first mechanism experiment uses an oracle-known guidance-change time only
to establish whether propagation lag exists. The deployable method then
replaces this with a causal trigger based on goal-distribution drift, edge-flow
drift, wait rate, and throughput decline. Event detection and repair allocation
must be ablated separately.

## Mandatory methods

All methods use the same candidate weights, starts, task stream, planner flags,
and seed.

1. `future_only`: official behavior; install weights, repair no active paths.
2. `random_B`: install weights and repair a seeded random matched budget.
3. `exposure_top_B`: proposed selection at the same budget.
4. `all_repair`: all-agent diagnostic oracle.
5. `no_update`: retain the old graph.
6. `GPIBT+LNS`: closest repair baseline, matched by A* time or call count.
7. `new_task_only_periodic`: official fixed-period weight-update family.

After the oracle-event pilot passes, add causal triggers:

- fixed periods `m ∈ {10,20,50,100,200}`;
- goal-drift threshold;
- wait/flow threshold;
- budgeted contextual action over `{none, 5%, 10%, 20% repair}`;
- hindsight event/repair oracle for headroom only.

## Phase 0 — propagation-lag audit

Use one official dynamic warehouse configuration at high density and 10 paired
seeds. At `+20`, `+50`, and `+100` steps after each workload shift, log:

- fraction of active agents still using a pre-shift guidance version;
- fraction whose remaining path contains materially increased-weight edges;
- natural guide-path turnover rate;
- new-task A* count;
- generator, assignment, A*, PIBT, and total wall time.

Proceed only if at least 40% of active agents still use pre-shift paths after 50
steps. If that fraction falls below 20% by 20 steps, natural task turnover is
too fast and selective repair is a No-Go on that setting.

## Phase 1 — mechanism pilot

Initial matrix:

- maps: `warehouse-33-57`, `sortation-33-57`, `empty-32-32`;
- densities: one medium and one high setting from official configs;
- shifts: abrupt Gaussian hotspot reversal and recurrent `A→B→A`;
- 10 paired development seeds, followed by 20 untouched validation seeds;
- horizon and task assignment identical to the pinned OnlineGGO protocol.

Primary comparison: `exposure_top_20` versus `random_20`, averaged per seed over
dynamic warehouse and sortation conditions.

## Metrics and attribution

Primary:

- total throughput;
- throughput in the first 100 and 200 post-shift steps;
- recovery time to 95% of `all_repair`'s phase rate;
- number and wall time of extra guide-path A* calls.

Secondary:

- fraction of `all_repair` recovery gain captured;
- wait ratio per active-agent timestep;
- path stretch and weighted path cost;
- stale-guidance cohort completion time;
- controller/scoring overhead;
- planning P50/P95/P99 and timeouts;
- collisions, edge swaps, deadlocks, and task-stream equality.

Do not attribute ordinary new-task A*, PIBT execution, or simulator stepping to
refresh savings. Generator, assignment, repair A*, and execution times remain
separate raw fields.

## Go / No-Go

The selective-repair direction proceeds only if all core conditions hold:

- `exposure_top_20` improves first-100/200-step post-shift throughput by at
  least 5% over `future_only` and `random_20`, with paired 95% CI lower bound
  above zero;
- total episode throughput improves by at least 3%;
- no more than 20% repair calls capture at least 70% of the `all_repair`
  recovery gain;
- end-to-end time increases by no more than 10%;
- static-workload degradation is no worse than 2%;
- zero added collisions/deadlocks and identical task streams.

No-Go conditions include no stable advantage over random selection or LNS,
benefits limited to the custom corridor map, rapid natural path turnover, or an
inability to reproduce the basic official baseline ordering.

## Statistical protocol

- Scenario seed is the unit of analysis.
- Pair every method on identical simulator/task seeds.
- Pre-register one primary comparison and one post-shift window.
- Use a paired exact sign-flip test when seed count permits and a 10,000-sample
  seed-block bootstrap interval.
- Report every paired seed, raw throughput, A* calls, and wall time.
- Do not select trigger thresholds or repair budgets on locked validation/test
  seeds.
