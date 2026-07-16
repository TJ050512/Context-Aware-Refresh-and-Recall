# DAI 2026 research design

Last updated: 2026-07-13

## Source-audit revision

The official OnlineGGO/GPIBT source audit changed the method after this design
was drafted. Supplying new `map_weights` does not globally refresh active guide
paths; it only affects later path-generation calls. Therefore the original
story that `reuse` avoids an expensive global planner refresh is not valid for
this backbone. The locked local smoke result remains a mechanism diagnostic,
not evidence for the official semantics.

The selective guide-path repair follow-up subsequently failed its locked local
mechanism gate: eager all-artifact repair was harmful and exposure-based Top-25
was not established. The current paper direction is **cohort-aware guidance
versioning**, documented in `GUIDANCE_VERSIONING_EXPERIMENT.md`. The source
evidence and integration contract are in `OFFICIAL_BACKBONE_AUDIT.md`. Sections
below describing a binary refresh/reuse controller are retained as an audit
trail and possible trigger machinery, but they are superseded wherever they
assume global replanning or large planner-cost savings.

## Executive decision

The project contains a real and useful mechanism signal: congestion-aware routing helps when traffic exceeds the capacity of a preferred corridor. That is a good starting observation, but the current method and experiments are not yet publishable evidence.

The original claim—selecting a global congestion weight from an agent-density bucket—is already weaker than a tuned fixed policy in a small audit and overlaps heavily with existing traffic-guidance work. Broad “LMAPF SOTA” is not a credible three-week target: recent systems evaluate thousands to tens of thousands of agents. A narrow and defensible target is still possible:

> Under previously unseen, non-stationary lifelong warehouse workloads,
> propagate changed traffic guidance to the most affected active agents under
> a matched guide-path replanning budget.

This target is only permitted after the correctness gate and strong public-baseline comparisons succeed.

## Why the question has research value

Existing work demonstrates that congestion guidance matters, but commonly optimizes a policy or graph before deployment, assumes a known workload family, uses a fixed update schedule, or studies one-shot MAPF rather than lifelong throughput.

- [Traffic Flow Optimisation (AAAI 2024)](https://arxiv.org/abs/2308.11234) continuously uses predicted path traffic to improve guide paths, so “use congestion to reroute” is not itself novel.
- [Guidance Graph Optimization (IJCAI 2024)](https://arxiv.org/abs/2402.01446) performs expensive offline edge-weight optimization.
- [Online GGO (AAAI 2025)](https://arxiv.org/abs/2411.16506) dynamically generates guidance from real-time traffic and changing task distributions. Its policy is nevertheless optimized offline with CMA-ES, commonly using 10,000–50,000 simulator evaluations per configuration, and it uses fixed update schedules.
- [RL-RH-PP (2026)](https://arxiv.org/abs/2603.23838) learns global priority orders for rolling-horizon planning and is a direct learning-based lifelong baseline. Its contextual-bandit ablation is weaker than multi-step RL, so a generic myopic bandit cannot be the whole contribution.
- [STEAM (2026)](https://arxiv.org/abs/2605.20929) already claims training-free test-time congestion enhancement, but for pretrained decentralized policies and mainly one-shot MAPF metrics.
- [LSMART (2026)](https://arxiv.org/abs/2602.15721) shows that invocation timing, planning budgets, execution uncertainty, and failure policies materially affect realistic lifelong fleet systems.

The defensible gap is therefore not “online congestion awareness.” It is **budget-constrained, event-triggered refresh of an existing strong guidance generator under unknown workload changes**. Online GGO fixes the refresh interval; LSMART has event-triggered planner invocation, but its trigger is whether queued actions will run out rather than the marginal value of guidance or a learned compute budget.

## Current project assessment

### Assets worth keeping

- A controllable two-route congestion mechanism suitable for debugging.
- A reproducible density sweep and basic ablations.
- A congestion-weighted shortest-path implementation that can become one arm in a stronger controller.
- AI2-THOR visualizations that can later illustrate motivation or transfer.

### Claims that must be retired

- Calling the current lookup table “online RL” or a trained contextual bandit.
- Claiming adaptive superiority without comparing every fixed scale and a validation-selected global fixed policy.
- Calling the custom recursive executor PIBT without reference-implementation equivalence and collision invariants.
- Treating the hand-built two-corridor map as an external benchmark.
- Reporting a minimum over eight seeds as worst-case robustness.
- Combining one-shot MAPF success/SOC with lifelong throughput in one SOTA table.

See `KNOWN_VALIDITY_ISSUES.md` for the complete audit.

## Proposed paper formulation

### Working title

**Budgeted Event-Triggered Guidance Refresh for Non-Stationary Lifelong MAPF**

### Problem

At decision epoch `k`, a lifelong MAPF system observes a compact traffic state `x_k` and chooses `u_k ∈ {reuse cached guidance, refresh guidance}`. A refresh calls a frozen guidance generator and incurs measured compute cost `c_k`; reuse is cheap but risks stale guidance. After the next window, the controller observes throughput feedback. The task-origin/destination process, active fleet size, topology, and congestion regime may change at unknown times.

The objective is to maximize cumulative completed tasks subject to an average or per-step real wall-clock budget and collision safety:

`maximize Σ r_k`, subject to `(1/K) Σ u_k c_k ≤ B`.

Evaluation compares against the full family of tuned fixed refresh periods, simple event triggers, public LMAPF solvers, and a hindsight refresh oracle.

### Frozen guidance generator and refresh action

The paper contribution does not replace Online GGO or claim a better guidance graph generator. The first backbone should be Online GGO with PIBT. At each decision point, the proposed layer only chooses whether to reuse its cached graph or pay to refresh it.

This separation is important:

- Online GGO answers **how to generate guidance**;
- the proposed method answers **when the expected marginal throughput benefit justifies refresh cost**;
- a second frozen guidance backbone is required before claiming the trigger is planner- or generator-agnostic.

Legacy congestion scales remain useful internal controls, but a scalar-weight selector is not the paper method.

### Traffic context

Use only information available during deployment:

- active/free-space density;
- recent throughput and normalized wait rate;
- conflict, backtracking, or failed-move rate;
- edge-load maximum/mean and entropy;
- opposite-direction flow;
- task-origin/destination hotspot entropy and cross-region demand;
- previous guidance action and switching history;
- guidance age;
- Jensen–Shannon divergence between the current goal distribution and the distribution at the last refresh;
- edge-usage distribution drift since the last refresh;
- throughput EWMA decline;
- the previous refresh's measured cost and recent planning-time statistics.

Probabilistic traffic-flow features are preferred to a single currently selected shortest path because equivalent paths otherwise make the congestion estimate unstable.

### Recommended controller

Use a sliding-window cost-sensitive contextual bandit with an online budget multiplier:

1. Aggregate cheap traffic and workload features over a short observation window.
2. Maintain sliding-window reward estimates for `reuse` and `refresh`.
3. Refresh when the optimistic marginal value exceeds predicted cost and a hysteresis margin:
   `UCB_refresh(x_k) - UCB_reuse(x_k) > λ_k ĉ_k + h`.
4. Update the non-negative dual variable online:
   `λ_(k+1) = [λ_k + η(u_k c_k - B)]_+`.
5. Record real refresh wall-clock time; update count alone is not an acceptable cost proxy.
6. Use change features to forget stale evidence, while a safe fallback prevents persistent gridlock.

Short counterfactual rollouts should be used only to construct a hindsight diagnostic oracle. They should not be the deployed algorithm: STEAM already predicts congestion by rolling out shortest paths, while RL-RH-PP already studies rolling-horizon Top-K quality–runtime trade-offs.

## Research questions and falsifiable hypotheses

### RQ1 — Is event-triggered refresh better than periodic refresh?

**H1.** Under stationary workloads, the controller should match the best tuned fixed refresh period within a pre-registered non-inferiority margin. Under unknown shifts and an equal refresh or wall-clock budget, it should obtain higher throughput and faster recovery than every fixed period.

Failure condition: no meaningful gain over the best point on the fixed-period throughput–runtime frontier.

### RQ2 — Is the trigger genuinely workload- and traffic-driven?

**H2.** Goal-distribution drift, edge-usage drift, guidance age, wait, and throughput-decline features should outperform density-only and hand-tuned threshold triggers on unseen maps and density ratios.

Failure condition: removing all features except density does not degrade paired test performance.

### RQ3 — Does online budget control matter?

**H3.** The dual budget update should satisfy the registered compute budget with fewer violations than an unconstrained trigger, while hysteresis reduces redundant refreshes without erasing throughput gains.

Failure condition: safety components only add latency or the unconstrained variant dominates on all registered metrics.

### RQ4 — Does the trigger generalize across guidance backbones?

**H4.** Under a shared time budget, the trigger should improve the throughput–runtime Pareto frontier of at least two frozen guidance backbones compared with each backbone's periodic refresh family.

Failure condition: gains occur only on the custom Python executor or only under a biased task generator.

## Baselines

### Internal controls — mandatory

1. No guidance / shortest paths.
2. Static/offline GGO.
3. Always reuse and always refresh.
4. Online GGO fixed refresh periods `m ∈ {10, 20, 50, 100, 200}`.
5. Best fixed period in hindsight, shown as an oracle rather than a deployable method.
6. Wait-rate threshold and goal-distribution-change threshold.
7. Current density lookup, renamed as an offline lookup baseline.
8. Proposed method without sliding window, budget dual, hysteresis, or change features.
9. A counterfactual rollout refresh oracle used only for diagnostic headroom.

### Direct public lifelong baselines — mandatory for a SOTA claim

1. [PIBT2](https://github.com/Kei18/pibt2), a scalable rule-based MAPF/MAPD baseline.
2. [RHCR-PBS or RHCR-ECBS](https://github.com/Jiaoyang-Li/RHCR), a classic strong rolling-horizon lifelong baseline.
3. [WPPL or EPIBT](https://github.com/Straple/LORR24), a strong competition-derived baseline.
4. Traffic Flow Optimisation or Guided-PIBT, the closest handcrafted online traffic-guidance baseline.
5. [Online GGO](https://github.com/zanghz21/OnlineGGO), the closest learned dynamic-guidance baseline.
6. [RL-RH-PP](https://github.com/MikeZheng777/RL-RH-PP), the recent learning-guided rolling-horizon baseline.

### Contextual but not main-table baselines

LaCAM, EECBS, MAPF-LNS2, LNS2+RL, and STEAM mainly target one-shot MAPF or a different execution setting. They can appear in a routing appendix or related work, but cannot replace direct lifelong throughput comparisons.

If task assignment remains a claimed contribution, the project also needs current online MAPD flow-based assignment baselines. The recommended paper scope instead fixes the task stream and assigner across methods, isolating traffic guidance.

## Benchmarks and data split

### Stage 0 — mechanism smoke test

Use the existing two-corridor map only to verify invariants, logging, and whether adaptation moves away from an overloaded corridor. No paper SOTA claim may rely on this stage.

### Stage 1 — direct reproduction maps

Use the map families shared by GGO/Online GGO where possible:

- `warehouse-33-57`;
- `sortation-33-57`;
- `empty-32-32`;
- `random-32-32`.

### Stage 2 — external generalization

Use standard held-out families such as:

- `warehouse-10-20-10-2-1`;
- `maze-32-32-4`;
- `room-64-64-16`;
- selected League of Robot Runners warehouse/sortation instances.

The POGEMA benchmark repository provides published LMAPF configurations, maps, seeds, episode lengths, and integrated algorithms. It is useful as a reproducibility layer, while the direct Online GGO and RL-RH-PP protocols remain necessary for apples-to-apples comparisons.

### Split policy

- Development maps and task regimes: implementation debugging only.
- Validation manifests: action portfolio, window size, discount, and thresholds.
- Test maps, densities, task streams, and change times: locked before final model selection.
- Every method receives identical initial states, releases, tasks, and planner time limits.
- Map seed, start seed, task seed, arrival seed, and policy seed are separate.

## Workload suite

Each dynamic episode lasts 1,200 steps with four 300-step phases for the pilot:

1. low-density uniform demand;
2. high-density top hotspot;
3. high-density hotspot reversal plus one corridor closure;
4. medium-density recovery with topology restored.

The full suite should include:

- abrupt hotspot shifts;
- gradual spatial drift;
- recurrent `A→B→A` demand;
- density shock;
- corridor closure/reopening;
- a mixed sequence with unknown boundaries.

Tasks must have explicit release times. Goals equal to current positions are forbidden unless separately modelled as zero-service tasks, and duplicate-goal semantics must be identical across solvers.

## Metrics

### Primary

- throughput: completed tasks per timestep;
- cumulative and windowed dynamic regret versus the hindsight refresh oracle for each phase;
- post-change recovery time to 95% of the phase-oracle rate;
- planning-budget violation rate.
- refresh count and refresh wall-clock time.

### Secondary and safety

- task service time mean/P95/P99;
- wait ratio per agent-timestep;
- path stretch;
- deadlock/gridlock rate;
- Jain fairness or per-agent completion Gini;
- planning time P50/P95/P99 and timeouts;
- guidance switch count and adaptation overhead;
- meta-controller wall-clock overhead;
- vertex and edge-swap collisions, which must always equal zero.

## Statistical protocol

- Scenario manifest is the experimental unit.
- Use at least 10 development and 30 locked test manifests per core condition where compute permits.
- Pair all methods on identical manifests.
- Report paired effect sizes and 95% paired-bootstrap intervals.
- Pre-register either a paired permutation test or Wilcoxon signed-rank test for each RQ; apply Holm correction within each RQ family.
- Plot every seed or paired difference, not only means and shaded curves.
- Report median, lower-tail/CVaR, and tail latency in addition to means.
- Do not select a method on the test set or call a sample minimum “worst case.”

## Experiment matrix and staging

### Gate A — correctness

- 6 procedural/standard layouts × 100 seeds × 1,000 steps.
- Zero vertex conflicts, edge swaps, invalid goals, or nondeterministic replays.
- Cross-check small instances against a reference solver.

### Gate B — 72-hour mechanism value

- First reproduce a frozen Online GGO evaluator and measure each refresh's actual cost.
- 2 maps × 2 densities × 3 shift types × 10 paired development manifests with random, unknown switch times.
- Compare the complete periodic family, both threshold triggers, always-refresh, and the proposed method.
- Proceed only if either (a) equal refresh budget yields at least 5% more throughput than best periodic, or (b) throughput loss is at most 1% while refresh count falls at least 40% and end-to-end runtime falls at least 25%.
- Adaptation delay after a change must fall at least 25%.

### Gate C — day-7 external value

- At least 3 public maps, 2 densities, and abrupt/gradual/recurrent task-distribution changes with 20 paired seeds per condition.
- Static-workload throughput degradation must be no more than 2%; budget violation rate no more than 5%.
- At least 70% of dynamic conditions must have paired 95% intervals excluding zero.
- Throughput–runtime Pareto hypervolume must improve by at least 8%–10% over the complete periodic family.
- RL-RH-PP, RHCR/RH-PP, and WPPL/EPIBT remain useful absolute-throughput references but do not replace the within-backbone refresh comparison.

### Gate D — robustness and ablation

- unseen map family, unseen density ratio, and unseen OD shift;
- context-feature groups;
- decision window and sliding-window length;
- workload/traffic change features;
- budget dual and hysteresis;
- real wall-clock cost versus refresh-count proxy;
- throughput–runtime Pareto curve.

## What counts as SOTA

The phrase “state of the art” may be used only if all of the following hold:

1. The protocol and claim are explicitly restricted to non-stationary, cold-start, equal-budget lifelong warehouse workloads.
2. For the same frozen online guidance generator, the method improves the throughput–runtime Pareto frontier over every tuned fixed refresh period on locked, held-out scenarios.
3. Gains survive paired inference and are not due to a different task assigner, time budget, hardware path, or invalid collisions.
4. A second guidance backbone reproduces the trend, and the public implementation, manifests, and raw per-seed results reproduce the tables.

Otherwise the paper should claim a new problem formulation, a safe deployment-time adaptation method, and competitive—not SOTA—results.

## Three-week execution plan

### July 13–15: scientific foundation

- Freeze scope to routing/guidance; preserve original coursework as provenance.
- Replace/fix PIBT execution and task generation.
- Add invariants, real arrival schedules, scenario manifests, and corrected statistics.
- Reproduce the official Online GGO evaluator, instrument true refresh costs, and run PIBT/RHCR starter cases.

### July 16–20: pilot and method freeze

- Run all fixed refresh intervals and simple event-trigger controls.
- Implement the budgeted event trigger and its ablations.
- Use short lookahead only as a diagnostic refresh oracle.
- Make a go/no-go decision by July 20; freeze method and test protocol.

### July 21–27: main experiments and paper skeleton

- Run direct public baselines and locked paired experiments.
- Complete generalization and critical ablations.
- Draft problem, method, related work, and experiment sections in the DAI eight-page format.
- Register the abstract by the conference abstract deadline.

### July 28–August 2: audit and writing

- Re-run failed seeds, verify raw-to-table pipeline, and audit all claims.
- Finish figures, limitations, reproducibility statement, and anonymous package.
- Reserve August 3 for final PDF and submission checks only.

## Immediate next implementation tasks

1. Add transactional collision-safe execution or integrate PIBT2.
2. Add `ScenarioManifest` and time-based task arrivals.
3. Integrate the existing per-step invariants into every rollout and add deterministic replay tests.
4. Reproduce official Online GGO inference and instrument refresh wall-clock cost.
5. Implement `reuse/refresh` controls, the full fixed-period family, and two threshold triggers.
6. Implement the budgeted event trigger behind the existing controller interface.
7. Generate the first 10 development manifests and enforce the 48/72-hour go/no-go gates.
