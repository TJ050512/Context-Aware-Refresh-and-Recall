# Current experiment: route-cohort-aware guidance publication

Date: 2026-07-13

## Working title

**Route-Cohort-Aware Event-Triggered Guidance Publication for Non-Stationary
Lifelong Multi-Agent Path Finding**

## Current scientific decision

The official GPIBT implementation gives guidance updates a natural versioned
semantics: a published edge-weight graph affects guide paths generated for
future tasks, while in-flight tasks keep their existing guide paths. A locked
potential-field diagnostic supports preserving this boundary:

- publishing the correct new guidance for future tasks improved total
  throughput by 13.79% over never updating (95% paired-bootstrap CI
  [7.75%, 20.32%], exact sign-flip p=0.000488);
- eagerly rebinding every active artifact reduced total throughput by 10.59%
  relative to future-only publication (CI [-14.83%, -5.98%], p=0.003418);
- exposure-top-25 did not beat random-25 significantly and produced no total
  throughput gain.

These are local smoke results, not OnlineGGO/GPIBT results. They reject the
selective-repair mechanism currently implemented and motivate an official
experiment on **when to publish a new guidance version**, without retroactively
changing in-flight tasks.

## Problem formulation

At publication epoch `k`, the system has a current guidance version `v_k` and
observes causal traffic/task features `x_k`. It chooses:

- `reuse`: keep `v_k` for guide paths constructed in the next window;
- `publish`: call a frozen guidance generator and install `v_(k+1)`.

A **route cohort** is defined by the normalized guidance graph used when a
guide path is actually constructed. Task reveal/assignment time is not used as
a proxy: queued tasks may become active after a later publication. The primary
configuration fixes `GUIDANCE_LNS=OFF`, so a route normally retains its build
version until the task changes. Any rebuild is nevertheless logged as a new
exposure. Cohort service summaries are controller feedback and diagnostics,
not unadjusted causal comparisons because version, time, phase, and task
difficulty are confounded. Primary effects are estimated from paired episode
outcomes with the same starts and fixed task stream.

The objective is lifelong throughput and stable post-shift recovery, with a
switch/publication regularizer. This is not framed as saving an expensive
global planner call: reuse only skips generator/action publication while
ordinary GPIBT, PIBT, and new-task A* work continue.

## Causal controller

The first deployable controller is deliberately simple:

1. Aggregate goal-distribution JS divergence, edge-flow JS divergence, wait
   rate, recent throughput decline, version age, new-route count, and fraction
   of active guide paths on the current version.
2. Do not evaluate a version until a minimum cohort size or maturity is met.
3. Publish when estimated marginal cohort value exceeds a hysteresis/switch
   penalty and a hard publication-rate token is available.
4. Attribute delayed descriptive feedback to the version that built the route;
   never use the next five simulation steps as if they were caused entirely by
   the newest publication.
5. Reset online learning per episode and freeze all hyperparameters before
   locked test manifests.

Start with a drift threshold and a change-point detector. Add the sliding-window
contextual confidence model only if those controls leave reproducible headroom.

## Baselines

Within the same frozen generator/backbone:

1. never publish after bootstrap;
2. publish every eligible window;
3. fixed periods `m ∈ {10,20,50,100,200}`;
4. fixed number of newly constructed guide paths per version;
5. goal-JS threshold;
6. edge-flow/wait threshold;
7. causal change-point detector;
8. proposed cohort-aware controller;
9. oracle shift-time publication for diagnostic headroom only.

Absolute public references remain PIBT, Guided-PIBT/TFO, static/offline GGO,
Online GGO, RHCR/WPPL where reproducible. They do not replace the within-backbone
publication-schedule comparison.

## Required instrumentation

The local adapter passes an explicit publication version/raw-action hash and
records generator and simulator time. The pinned, uncompiled trace patch also
records the hash of the **normalized weights actually sent to C++**, exact
half-open window bounds, flat task events, timestep-keyed planner records,
build flags, and every guide-path construction caused by INIT_PP or a task
change. Each construction is bound to agent, task, goal, execution timestep,
internal weight revision, publication version, and raw/applied hashes. The
compiled binary hash must still be archived by the Linux runner.

The old `GuidanceCohortTracker` remains an assignment-event prototype only.
The new `RouteCohortTracker` joins completions to actual construction events
and deliberately rejects a completion without a recorded route build. The
C++/Python trace patch remains uncompiled and must pass schema, replay, and
route-build sentinel tests on Ubuntu x86_64 before either tracker supports a
paper result.

## First official experiment

Gate 0A is a semantic and replay gate, not a performance comparison:

- pin and log source commit, compiler, compile flags, binary hash, and
  `GUIDANCE_LNS=OFF`;
- verify RDLU action channels on an asymmetric map and hash the normalized
  weights installed in C++;
- replace ignored/reset randomness with fixed starts and an exogenous task
  tape, then require byte-identical cached-action replay;
- verify exact non-overlapping event windows and direct guide-path build
  events, including the publication-boundary case;
- separate generator, guide-path construction, PIBT, serialization, and total
  time where the source permits it.

Only after Gate 0A passes does Gate 0B use one dynamic warehouse configuration
and 10 paired development seeds to reproduce reference ordering and compare no
publication, always publication, periods 20/50/100, and an oracle-shift
diagnostic. It asks whether any controllable schedule headroom exists.

Gate 1 expands to warehouse, sortation, empty, and random maps at medium/high
density with abrupt and recurrent shifts. Test seeds and task streams are
locked before controller selection.

## Primary endpoints and Go/No-Go

Primary comparison: cohort-aware publication versus the best validation-tuned
fixed schedule under the same frozen generator.

Go requires one of:

- at the same publication count, at least 5% higher dynamic-workload throughput
  with paired CI lower bound above zero; or
- no more than 1% throughput loss with at least 40% fewer publications, plus a
  demonstrated operational cost such as generator/communication time.

Additionally:

- total throughput must improve at least 3% on the primary dynamic suite;
- static degradation must be no worse than 2%;
- both warehouse and sortation directions must be nonnegative;
- the causal drift trigger must beat a simple threshold before adding a learned
  controller;
- zero collision, edge-swap, task-stream, or replay violations.

No-Go if fixed schedules dominate, route-cohort feedback is too delayed/noisy,
the generator update cost is negligible and quality is unchanged, or the
effect exists only in custom corridor maps.

## External dependency blocker

The official checkout has no released trained OnlineGGO checkpoint, and this
Mac is not compatible with the pinned Python 3.9/x86_64 build. The next
claim-bearing run requires an Ubuntu x86_64 environment and either an
author-provided checkpoint or a fresh CMA-ES training run. Until then, results
remain infrastructure and smoke evidence only.
