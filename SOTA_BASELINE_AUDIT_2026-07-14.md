# SOTA / Baseline Audit for Budgeted Guidance Publication

Date: 2026-07-14  
Scope: non-stationary lifelong MAPF with a frozen OnlineGGO `[p-on]+GPIBT` backbone and a causal controller deciding when to publish/reuse the shared guidance graph.

> **Protocol update.** The original planning notes later in this document are
> retained as audit history, but their four-workload/seed-101--110 run plan and
> preliminary thresholds are superseded by
> `configs/claim_validation_protocol_v2.json`. The live claim-bearing design has
> three absolute-release workloads, fresh validation-v2 seeds, four
> map--density cells, 13 methods, and root-seed-cluster inference. Seeds
> 101--110 are contaminated pilot evidence. The current paper-facing source of
> truth is `PAPER_METHOD_EXPERIMENTS_DRAFT.md`.

## Executive decision

This direction remains scientifically viable, but the defensible claim is **not** “SOTA in lifelong MAPF” or “SOTA in non-stationary MAPF.” The literature audit found no directly aligned public method that learns a causal binary publish/reuse policy for a globally shared OnlineGGO guidance graph under a hard publication budget. Therefore, the right target is:

> To our knowledge, the first causal, budget-constrained guidance-publication controller for a frozen shared OnlineGGO `[p-on]+GPIBT` backbone under non-stationary absolute-release Kiva workloads.

If the locked tests pass, the result may be described as:

> The proposed controller improves/establishes the throughput–publication Pareto frontier among the evaluated publication controllers on the fixed-tape benchmark.

Prefer “best evaluated controller” or “new Pareto frontier” over an unqualified “SOTA,” because the task category and fixed-tape benchmark are new. SOTA is an empirical conclusion, not an experiment target that can be guaranteed in advance.

## Executable-baseline readiness on the current instance

The formal 13-controller matrix already includes the directly runnable
same-backbone anchors: `always` (OnlineGGO-style periodic `[p-on]+GPIBT` at
$D=20$), `uniform` (all-one guidance/zero CNN), `bootstrap_only`, `period_80`,
and `exact_even_B25`. They share the pinned `period_on_sim` binary, frozen 10k
checkpoint, starts, absolute task tapes, maps, and safety instrumentation. The
10k checkpoint is adapted local training, so these are **OnlineGGO-style
same-backbone baselines**, not an official end-to-end OnlineGGO reproduction.

The checkout contains Guided-PIBT, WPPL, and RHCR source fragments but no
separate runnable binaries aligned to this protocol. WPPL also lacks the
absolute-release tape adapter and still generates Kiva tasks online. LLLG,
SILLM, EPIBT, RL-RH-PP, and the official AIJ PIBT implementation are absent.
Adding one fair external solver requires at least 120 validation-alignment runs
(four scenarios, three workloads, ten roots), plus a separately frozen adapter,
binary, timeout policy, replay check, and safety audit; a locked comparison adds
360 runs per solver. Consequently, no current result can support “global LMAPF
SOTA” or claim superiority to those systems.

## Most important correction to the current protocol

With decision interval `D=20` and scored horizon `H=2000`, there are `N=H/D=100` scored windows and decision indices `0..99`. Decision 0 installs the mandatory bootstrap graph and advances the first scored window. Because bootstrap is excluded from the quota, there are only `K=N-1=99` post-bootstrap eligible decisions. At `B25`, every main method must therefore make exactly `ceil(0.25*99)=25` post-bootstrap publications, or 26 total generator calls including bootstrap.

The exact evenly spaced comparator is an integer-quota schedule, not an ordinary fixed period. For quota `B`, publish at eligible decision index `d=1..K` iff `floor(d*B/K) > floor((d-1)*B/K)`. The quotas are:

- `B10`: `ceil(0.10*99)=10` post-bootstrap publications;
- `B25`: `25` post-bootstrap publications at indices `4,8,12,16,20,24,28,32,36,40,44,48,52,56,60,64,68,72,76,80,84,88,92,96,99`;
- `B50`: `ceil(0.50*99)=50` post-bootstrap publications;
- `B100`: `99` post-bootstrap publications (all eligible decisions).

The current fixed-period grid does not contain an exact quota-matched primary comparator. A nominal `m80` refreshes at decision indices `0,4,...,96`: that is bootstrap plus only 24 post-bootstrap calls, not `B25=25`. Comparing a 25-publication learned controller only against `m100` or nominal `m80` is not exact-count matching. Add `exact-even-B25` and keep `m40/m50/m80/m100/m200` as secondary cadence references.

All counted methods must use the same budget convention: either bootstrap is excluded for every method or included for every method. Report both total generator calls and post-bootstrap calls to remove ambiguity.

## Primary-source audit

### OnlineGGO — AAAI 2025

- Paper: <https://ojs.aaai.org/index.php/AAAI/article/view/33614>
- Official PDF: <https://ojs.aaai.org/index.php/AAAI/article/download/33614/35769>
- Appendix/workshop version: <https://womapf.github.io/aaai-25/pdf/Submission_26.pdf>
- Official code: <https://github.com/zanghz21/OnlineGGO>

Key facts relevant to comparability:

- Main maps are sortation-33x57, warehouse-33x57, empty-32x32, and random-32x32, with additional warehouse-large and game maps.
- Dynamic Gaussian/multimodal-Gaussian centers are resampled every 200 simulator timesteps. Kiva goals alternate between workstations and endpoints.
- Main evaluations run 1,000 simulator steps and average 50 simulations with 95% confidence intervals.
- `[p-on]+GPIBT` publishes a globally shared learned guidance graph periodically; the main setting uses `m=20`.
- `on+GPIBT` evaluates learned guidance while individual guide paths are searched. It is not a publication scheduler.
- `off+GPIBT` is the offline optimized guidance anchor; `hm+GPIBT` is a human-designed guidance anchor.
- The published interval study for `on+PIBT` uses `m in {10,20,50,100,200}` and separately optimizes each policy. It shows that smaller intervals can improve throughput at higher runtime cost. It does not learn an event-triggered schedule and is not a direct same-backbone publication-controller baseline.
- The official warehouse-d `[p-on]+GPIBT` optimization uses 50,000 CMA-ES evaluations, batch size 100, and two simulator rollouts per candidate. A 2,000-evaluation/one-rollout run is a pilot, not an official reproduction. A 50,000-evaluation/one-rollout checkpoint must be labeled an **adapted one-rollout training run**, not an official-equivalent reproduction.
- The original simulator samples a new task when an agent completes its current task. A fixed absolute release tape changes the estimand. Published OnlineGGO throughput numbers cannot be copied as numerically aligned baselines for that benchmark.

### Guided-PIBT / Traffic Flow Optimization — AAAI 2024

- Paper: <https://pathfinding.ai/pdf/chls-aaai24-tfoflmapf.pdf>
- Official code: <https://github.com/nobodyczcz/Guided-PIBT>

Guided-PIBT builds congestion-aware guide paths and replans an agent when its task changes; optional path refinement can update selected paths every timestep. It is a strong online-guidance reference but not a binary global graph publication controller. Its maps, horizons, task process, and time limits differ materially from the proposed benchmark. It becomes an aligned competitor only if ported into the same fixed-tape harness with the same tasks, solver budget, and timeout.

### GGO — IJCAI 2024

- Paper: <https://arxiv.org/abs/2402.01446>
- Official code: <https://github.com/lunjohnzhang/ggo_public>

GGO is the appropriate static/offline guidance anchor. It does not adapt publication timing, but omitting an available offline graph would leave the guidance-quality story incomplete.

### PIBT

- Official implementation/page: <https://kei18.github.io/pibt2/>

Use the paper-facing name **PIBT (AIJ 2022 implementation)**. `pibt2` is the implementation/site name, not a distinct algorithm called “PIBT2.” PIBT/unweighted guidance is the no-learned-guidance anchor.

### Current broader LMAPF frontier (non-aligned references)

These methods matter if the paper ever makes a global LMAPF SOTA claim, but none is currently an aligned publication-controller baseline:

| Method | Primary source | Why not aligned now |
|---|---|---|
| LLLG, SoCS 2026 | <https://arxiv.org/abs/2605.16855>, <https://github.com/allegorywrite/lllg> | New real-time LMAPF solver; random goals and different maps/horizon, no hard guidance-publication budget. This is the most important newer omission in a global-SOTA comparison. |
| SILLM, ICRA 2025 | <https://arxiv.org/abs/2410.21415>, <https://github.com/DiligentPanda/Scalable-Imitation-Learning-for-LMAPF> | Learned planner on large-map settings; different solver/training/task regime. |
| WPPL / PIBT-LNS | <https://arxiv.org/abs/2404.16162>, <https://github.com/DiligentPanda/MAPF-LRR2023> | Competition setting with rotations, one-second step budgets, and different maps/tasks. `WPPL` is the correct spelling. |
| EPIBT, AAAI 2026 | <https://ojs.aaai.org/index.php/AAAI/article/view/40233> | League-of-Robot-Runners setting; task assignment/rotations and different objective constraints. |
| RL-RH-PP, JAIR 2026 | <https://arxiv.org/abs/2603.23838>, <https://github.com/MikeZheng777/RL-RH-PP> | Rolling-horizon prioritized planning with different maps, populations, horizon, and task process. |
| MGGO, 2026 | <https://arxiv.org/abs/2602.23468> | Offline edge-direction/weight optimization, not an online publication scheduler. |
| Congestion Prediction, ICRA 2023 | <https://www.amazon.science/publications/congestion-prediction-for-large-fleets-of-mobile-robots> | Predictive guidance in a production-like continuous-time simulator; not the same discrete LMAPF treatment and no aligned public controller. |

A global SOTA claim would require running the strongest relevant public solvers—at minimum LLLG, Guided-PIBT, OnlineGGO, PIBT, WPPL/EPIBT or a justified representative, and likely RHCR/SILLM—under one aligned map/task/horizon/timeout protocol. That is not a credible one-day experiment.

## Minimum strong same-backbone experiment matrix

Every main comparison below must share the **same frozen guidance checkpoint**, simulator build, task tape, initial states, seeds, and hard publication-budget guard.

### Anchors

1. `uniform`: no learned guidance and zero generator calls.
2. `offline/static GGO`: one static optimized graph, if a valid graph is available. If unavailable, mark it pending rather than substituting a fake proxy.
3. `bootstrap-only`: generate once at the first decision and reuse forever.
4. `always/m20`: publish at every D=20 decision; this is the B100 endpoint.

### Fixed schedules

1. `exact-even-B10`
2. `exact-even-B25` — **primary same-budget comparator**
3. `exact-even-B50`
4. `exact-even-B100` (equivalent to always after bootstrap)
5. `m40`, `m50`, `m80`, `m100`, and `m200` as cadence references

Do not include `m10` in a D=20 experiment: it cannot be represented on that decision grid. It belongs only in a separate D=10 replication.

### Budget-matched causal controllers at B25

1. `random-B25`: precommitted uniform random subset of exactly 25 decision indices, with an independent RNG stream.
2. `task/current-goal-JS-B25`: distribution-shift trigger with a hard quota guard.
3. `throughput-or-wait-drop-B25`: performance-degradation trigger with a hard quota guard.
4. `proposed-cohort-B25`: proposed causal controller with exactly 25 publications.
5. `proposed-no-cohort-B25`: key novelty ablation.

An event trigger that merely stops after spending its budget can waste all calls early. The hard guard should reserve enough quota for remaining decision windows, use a deterministic tie/budget rule, and log both requested and accepted publications.

### Oracles (diagnostic upper bounds only)

- Observed-shift oracle.
- Hindsight best-subset oracle.

Never report either oracle as an online baseline, because it uses privileged or future information.

## Run order for today

### Stage 1 — correctness/gate run

- Seeds 17–19.
- One official-compatible warehouse map/density.
- Workloads: stationary, abrupt shift, recurrent shift, gradual drift.
- Core methods: uniform, bootstrap-only, always, exact-even-B25, nominal m80, random-B25, JS-B25, proposed-B25, proposed-no-cohort-B25.
- Abort downstream claims if any task-tape fingerprint, task-ID, safety, determinism, or budget-count invariant fails.

### Stage 2 — development/validation

- Seeds 101–110, kept separate from locked test seeds.
- Same four workload families.
- Add m100, m40, throughput-drop-B25, and offline GGO if available.
- This stage selects/fixes thresholds. It cannot support the final significance claim.

### Stage 3 — locked test

- Freeze controller thresholds and code before looking at test results.
- Use untouched seed clusters; pair every method on identical initial state and task tape.
- Run at least two maps/backbones for a cross-map claim.
- Run proposed versus exact-budget periodic comparator at B10/B25/B50/B100 for a Pareto curve. Three nontrivial budgets plus endpoints is the minimum useful curve.

### Stage 4 — published-distribution bridge

Run a separate OnlineGGO-compatible bridge on warehouse-small/narrow with 400 agents, 1,000 steps, Gaussian center changes every 200 steps, and 50 seeds:

- Official-style `[p-on]+GPIBT, m20`
- Frozen proposed controller under the declared budget

Keep this bridge separate from the fixed-tape benchmark because the task-generation estimands differ. It contextualizes the method against OnlineGGO but does not magically make fixed-tape numbers comparable to the paper.

## Thresholds required for an honest claim

For a quality claim at B25, proposed versus `exact-even-B25` should satisfy all of:

- mean paired relative throughput improvement at least +2%;
- cluster-bootstrap 95% lower bound above zero;
- one-sided paired sign-flip/permutation p-value below 0.05;
- at least 60% seed-cluster wins;
- both tested maps positive and at least three of four workload families positive;
- stationary-workload degradation no worse than 1%;
- zero collisions, task-tape/fingerprint mismatches, nondeterministic treatment leakage, or budget violations.

For an efficiency claim:

- throughput difference at least -0.5%, with 95% lower bound above -1%;
- at least 40% fewer generator calls or generator time;
- at least 20% lower end-to-end wall time.

Wall-time claims require exclusive hardware allocation, randomized method order, warm-cache policy declared in advance, and per-component timing. At equal B25 generator-call count, a throughput gain is enough for the throughput–publication frontier, but not for a wall-time claim.

For a Pareto-frontier claim, the proposed controller must be non-dominated in both throughput–publication space and, if reported, throughput–generator-time/end-to-end-time space. Plot uncertainty intervals; do not infer dominance from point estimates alone.

## Paper wording that is safe now

Safe before final results:

> We study a previously underexplored control layer in online guidance generation: when a globally shared learned guidance graph should be republished under a hard compute budget. Unlike OnlineGGO's fixed periodic schedule, our controller uses only causal state and workload summaries and is evaluated with exact publication-count matching on paired task tapes.

Safe only after locked tests pass:

> On the proposed fixed-tape non-stationary benchmark, our method establishes the strongest evaluated throughput–publication trade-off among causal same-backbone publication controllers.

Unsafe without a much broader aligned comparison:

- “state of the art in lifelong MAPF”;
- “state of the art in non-stationary MAPF”;
- “outperforms OnlineGGO” when the task process, horizon, checkpoint training, or solver budget differs;
- “official OnlineGGO reproduction” for one-rollout or shortened CMA-ES training.

## Go / no-go conclusion

**Go**, provided the contribution is framed as budgeted causal publication control and the `exact-even-B25` comparator is added immediately. The strongest credible one-day outcome is an MVP plus validation evidence that the proposed controller beats exact-count even and random scheduling on the same frozen backbone. A paper-worthy claim still requires locked seeds, at least two maps/backbones, multiple workload families, and a Pareto sweep. If the controller does not beat `exact-even-B25`, the current mechanism has not yet earned the central claim; report the negative result and redesign rather than calling it SOTA.
