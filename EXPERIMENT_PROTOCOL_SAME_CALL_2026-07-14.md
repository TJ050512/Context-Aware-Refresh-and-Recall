# Frozen same-call confirmation protocol

Date: 2026-07-14  
Status: **experimental design and method semantics frozen before implementation and before any fresh-root run**  
Evidence target: a scoped DAI Research Track claim on a frozen OnlineGGO-style
CNN+GPIBT backbone; never a global lifelong-MAPF SOTA claim.

## 1. Decision this protocol is allowed to make

The focal treatment is the unchanged `context_memory_B25` controller from
validation-v2. The paper question is:

> Does causal context-selective guidance publication form a reproducible
> throughput--generator-call Pareto point, and does it remain within a 1%
> non-inferiority margin of a 26-call evenly scheduled reference?

Validation-v2 already found `context_memory_B25` versus `bootstrap_only`
`+5.30%` (95% root-cluster CI `[+3.69%, +7.28%]`) and versus
`exact_even_B25` `+0.03%` (CI `[-0.57%, +0.59%]`), using 5.483 rather than 26
mean total generator calls. It nevertheless failed its original 80% call and
mean-switch gates. This protocol is therefore an explicitly post-validation,
new-root confirmation of a narrower Pareto claim. It must not be described as
the original gate having passed.

`context_dualcap_G4S5` and `context_eventreserve_G5S6` are negative
development results, not candidates in this confirmation. Event-reserve was
`-1.17%` versus `exact_even_B25` and `-0.37%` versus the original context
controller. No G/S threshold may be tuned after this freeze.

Selective route repair is out of scope and prohibited. Its historical locked
diagnostic found all-repair versus lazy `-10.59%`, Top-25 versus lazy `-0.29%`,
and no established advantage over random repair. Counterfactual value models,
selective repair, LLLG adapters, and other solver changes require a separate
future protocol and new roots.

## 2. Fixed simulator and workload design

Every run uses:

- warm-up: 200 simulator steps;
- scored horizon: 2,000 steps;
- decision window: 20 steps, hence 100 scored windows;
- mandatory bootstrap at decision 0 for every non-uniform method;
- 99 post-bootstrap eligible decision indices, `1..99`;
- release interval per agent: 110;
- guard suffix: 4 tasks per agent;
- workloads: `stationary`, `abrupt`, and `recurrent`;
- absolute-release tapes, with no completion-driven workload RNG;
- the frozen 10k CNN checkpoint and pinned `period_on_sim` binary.

The four required scenario cells are:

| Cell | Map SHA-256 | Agents |
|---|---|---:|
| `narrow_r020` | `866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6` | 218 |
| `narrow_r035` | same narrow-map hash | 382 |
| `regular_r020` | `0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd` | 255 |
| `regular_r035` | same regular-map hash | 447 |

The independent unit is the root seed. Each method has 12 cells per root
(four scenarios times three workloads). No map, density, workload, root, or
failed arm may be dropped after a split is opened.

## 3. Frozen eight-method family

The confirmatory family is exactly:

1. `bootstrap_only`
2. `exact_even_G4`
3. `exact_even_G5`
4. `random_G5`
5. `js_cap_G5`
6. `context_no_reactivation_B25`
7. `context_memory_B25`
8. `exact_even_B25`

No ninth method may be added after the first fresh root is run. Development
failures may not be replaced by a newly tuned candidate on the same fresh
split.

### 3.1 Exact schedules

Bootstrap is outside every post-bootstrap quota.

- `exact_even_G4` has exactly four post-bootstrap generations at global
  decision indices `[25, 50, 75, 99]`, for five total generator calls.
- `exact_even_G5` has exactly five post-bootstrap generations at indices
  `[20, 40, 60, 80, 99]`, for six total calls.
- `exact_even_B25` uses the already frozen 25-post-call integer-quota schedule,
  for 26 total calls.

All exact schedules implement the same integer rule:

```text
publish at eligible index d iff
floor(d * B / 99) > floor((d - 1) * B / 99).
```

Unit tests must assert the complete index vectors, not only the counts.

### 3.2 Random and JS controls

`random_G5` selects exactly five distinct post-bootstrap indices before the
episode begins. Its RNG is independent of starts, task tapes, planner RNG, and
method order. It uses the existing keyed policy convention with method domain
`random_G5`; for a given root, its five indices are identical across all maps,
densities, and workloads. The selected indices are logged before the first
scored step.

`js_cap_G5` is the unchanged `js_cap_B25` score/persistence rule with only the
post-bootstrap generation cap changed from 25 to 5. It has no catch-up and no
forced fill, so it may use fewer than five post calls. Thresholds and pacing
logic may not be retuned.

### 3.3 Pure memory ablation

`context_no_reactivation_B25` keeps every score, threshold, persistence,
maintenance, route-maturity, minimum-gap, minimum-effect-window, and B25
switch/generation rule of `context_memory_B25`. The sole change is that
historical recall is unavailable. The controller retains the active
generation's context but ignores non-active catalog entries; it therefore
falls through the original remaining priority order:

1. maintenance-due -> propose a fresh generation;
2. active context matches -> hold;
3. otherwise -> propose a fresh generation.

It never executes `reactivate`. It is not call-matched by construction; its
actual calls are outcomes and must be reported. Mapping a recall proposal
directly to hold, changing a threshold, or imposing a G5 cap would be a
different ablation and is prohibited.

### 3.4 Actual-call fairness

`context_memory_B25` has a B25 hard ceiling but is empirically sparse; it does
not have a per-run G5 ceiling. Consequently, this study compares **actual mean
call use bracketed by fixed five- and six-total-call schedules**. It must not be
described as a strict equal-hard-budget comparison.

For every method report total calls and post-bootstrap generations as mean,
median, P90, maximum, and the fractions of runs with total calls at most 5 and
at most 6. Also report reactivations and effective switches. A same-call/Pareto
claim requires `context_memory_B25` to use no more than 6.0 total calls on
average in the fresh matrix. Per-run excesses above six remain visible.

## 4. Implementation freeze before any experiment

New code may implement only the five new method contracts above (G4, the three
G5 controls, and the no-reactivation ablation). It must not
change `context_memory_B25`, the observation, task generator, adapter, planner,
checkpoint, map, or workload semantics.

To preserve historical evidence, the frozen EventReserve `claim_runner.py` and
validation runner remain byte-identical at their archived hashes. Same-call
extensions live in versioned `same_call_claim_runner.py` and
`run_same_call_confirmation_v1.py` files; the new runner imports only the new
module. Historical analyzers must continue to verify their own archived source
snapshots rather than treating the mutable research tree as that snapshot.

The implementation manifest must be created before engineering smoke and must
contain SHA-256 hashes for at least:

- `claim_runner.py` and the validation runner;
- `publication_policy.py`;
- `frozen_cnn_generator.py`;
- `online_ggo_adapter.py`;
- OnlineGGO `trafficflow_online_env.py` and `task_generator.py`;
- checkpoint file and float32 parameter payload;
- `period_on_sim`, map files, this protocol, analyzer, and launcher;
- Python, PyTorch, NumPy, compiler, CUDA, OS, CPU, and GPU versions;
- all determinism flags and environment variables.

The pre-implementation base identities are recorded for drift detection:

| Artifact | SHA-256 |
|---|---|
| `claim_runner.py` | `d9bf61bfa2f86881084b2b1abc19aa0f7483206fa58dcdc88c0b086099d03c2e` |
| validation runner | `694c6af03421e653b7d273d6e5f9da3dd6d1ec349f9120b8efe06bf466b33d50` |
| `publication_policy.py` | `d860af7cc664ff30eaed6bad099313c27f74e99e933f95503d668d57b0ec6d88` |
| `frozen_cnn_generator.py` | `023126dd8ce34e8a65ae011f8a7dbb0cca754220b62920db812237de0285b7f2` |
| `online_ggo_adapter.py` | `013cae2734aa67782ae560e55eeb9b51c9be7343ab27e6ef2e3836ffcc1e913b` |
| `trafficflow_online_env.py` | `178d954b17f1bf33a1772fd481adb66709de221957dc41ae9c592e591ecfa5a4` |
| `task_generator.py` | `ae37b0c02bca7815af3d8e491507281ed92d85fa7ed91ec7ebe3ca44c889dbf5` |
| checkpoint file | `e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d` |
| checkpoint parameters | `6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac` |
| `period_on_sim` | `9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5` |

Any necessary behavior-code correction after smoke invalidates the manifest
and all smoke outputs. A new manifest and complete smoke rerun are required.
No behavior or analysis code may change after the first fresh-root run.

## 5. Stage E: engineering smoke on old roots

Old roots are used only for correctness, never effect estimation, method
selection, thresholds, claims, or Go decisions. Run all eight methods for root
17 over all 12 cells: **96 smoke runs**.

Smoke passes only if:

1. the active implementation, policy, simulator-interface, and analyzer unit
   suites pass; historical version-drift sentinels are separately checked
   against their matching archived source snapshots;
2. exact G4/G5 and random G5 have exact registered counts and schedules;
3. JS G5 never exceeds five post calls;
4. no-reactivation executes zero recalls and otherwise satisfies B25
   conservation;
5. `bootstrap_only`, `context_memory_B25`, and `exact_even_B25` reproduce their
   archived common-arm tasks, starts, tape hashes, release projection,
   completion trajectory, guidance hashes, and action timeline bit-for-bit,
   excluding only timing and explicitly listed method-order metadata;
6. two independent repeats of one representative arm have identical causal
   replay payloads;
7. a future-suffix metamorphic test holds: replacing every task/release after
   time `t` leaves all decisions, scores, observations, actions, and hashes
   before `t` bitwise identical;
8. every safety, pairing, route, and budget audit in Section 9 passes.

Smoke failure is an engineering stop. Fixing a genuine implementation defect
is allowed only before fresh evaluation, followed by a new manifest and all 96
smoke runs. Observed smoke throughput must not influence any rule.

## 6. Stage C: one-shot fresh confirmation

### 6.1 Frozen root vector

The fresh roots were deterministically derived before any member was run from
the completed EventReserve evidence archive:

```text
source SHA-256 = dedf2a8d840c27ff9482d626476c2bd14b3001e23196663225e579b484020c22
domain = dai-same-call-confirmatory-v1
s_i = 100000 + (int(SHA256(source|domain|i)[0:16], 16) mod 900000)
```

The authoritative vector is:

```text
[767369, 695428, 323681, 904171, 446020,
 434435, 488565, 514527, 544573, 838809]
```

Repository search found no prior use of these values as `root_seed`. At this
protocol freeze, zero runs on this vector exist. These are the only roots
permitted for Stage C.

### 6.2 Matrix and execution

Run 8 methods times 10 roots times 3 workloads times 4 scenarios:
**960 runs**. Once any fresh root is opened, all 960 outcomes are mandatory.

Each method arm runs in a fresh OS process to isolate Python, C++, and static
RNG state. Task tapes are materialized and hashed before treatment execution.
Method order uses an independent keyed RNG and cannot affect task, planner, or
publication streams. Artifacts are append-only and may not be overwritten.
Every scenario runner also writes an append-only attempt ledger before any arm
starts and after each arm completes. The ledger records the full cell identity,
host, parent and child process identities, process-start timestamp, run UUID,
planner/safety status, and a canonical hash of the emitted run. Unfinished,
failed, duplicated, or retried attempts cannot be silently discarded.

Do not calculate treatment effects, ranks, or provisional p-values while the
matrix is incomplete. Hardware interruption may restart the exact missing arm
from the beginning with a logged infrastructure-failure record. A method
exception, planner timeout, or safety failure is an outcome, not a deletable
run.

## 7. Frozen estimands and inference

For method `A` and comparator `B`, the root-level relative effect is

```text
d_i(A,B) = (1/12) * sum_c [(tasks_A,i,c - tasks_B,i,c) / tasks_B,i,c].
```

The 12 cells are equally weighted. Report all ten `d_i`, their mean, median,
root W/T/L, absolute task difference, both map effects, all three workload
effects, and leave-one-root-out means.

Intervals are 10,000-sample whole-root percentile bootstrap intervals with RNG
seed `20260715`. Superiority tests use the exact one-sided paired sign-flip test
over root effects. Ties are omitted only in the standard exact-test manner and
are always reported. No run-, task-, agent-, or window-level pseudo-replication
is permitted.

### 7.1 Primary superiority family and Holm correction

The focal method is `context_memory_B25`. The six predeclared superiority
contrasts are:

1. versus `bootstrap_only`;
2. versus `exact_even_G4`;
3. versus `exact_even_G5`;
4. versus `random_G5`;
5. versus `js_cap_G5`;
6. versus `context_no_reactivation_B25`.

Apply Holm step-down correction at family-wise alpha 0.05 to these six
one-sided exact sign-flip p-values. Report raw and adjusted p-values. CIs remain
effect-estimation intervals and must not be relabeled as multiplicity-adjusted.

### 7.2 Separate 1% non-inferiority test

The sole non-inferiority contrast is `context_memory_B25` minus
`exact_even_B25`, with relative margin `-1.00%`. For each root define
`z_i = d_i + 0.01` and run a one-sided exact sign-flip test of positive shifted
effect. Near-exact language requires all of:

- mean relative effect at least `-0.50%`;
- 95% root-cluster CI lower bound strictly above `-1.00%`;
- one-sided non-inferiority p-value below 0.05.

This singleton NI test is reported separately from the Holm superiority
family. The paper must disclose that the 1% margin was retained from the
earlier protocol while the Pareto hypothesis was formulated after
validation-v2.

## 8. Frozen outcome tiers

### Tier A — strong mechanism evidence

Tier A requires every Tier B condition plus:

- all six Holm-adjusted superiority p-values below 0.05;
- every corresponding unadjusted cluster CI lower bound above zero;
- context versus bootstrap mean effect at least `+2.00%`;
- context has positive mean effects versus all four sparse controls
  (`exact_even_G4`, `exact_even_G5`, `random_G5`, `js_cap_G5`);
- context versus no-reactivation is positive, licensing the specific statement
  that historical recall adds value;
- context versus `exact_even_G5` is positive on both maps and at least two of
  three workloads, with stationary degradation no worse than `-1.00%`.

Tier A licenses a scoped mechanism claim: Context-Memory improves sparse
publication allocation among the evaluated same-backbone controls while
remaining non-inferior to the 26-call reference.

### Tier B — Pareto result suitable for a scoped DAI paper

Tier B requires:

1. every audit in Section 9 passes;
2. context versus bootstrap has mean effect at least `+2.00%`, CI lower bound
   above zero, and Holm-adjusted one-sided p-value below 0.05;
3. the 1% NI test in Section 7.2 passes;
4. context uses at most 6.0 mean total generator calls and reduces mean calls
   by at least 75% versus `exact_even_B25`;
5. context is not point-estimate dominated in `(mean total calls, mean tasks)`
   by any of the other seven methods;
6. context versus bootstrap is positive on both maps and all three workloads;
7. zero selective cell deletion, timeout deletion, or analysis-family change.

Here method A point-dominates B only if A has no fewer mean tasks and no more
mean total calls, with at least one strict inequality. Plot uncertainty and
actual call distributions; point-frontier membership is not statistical
superiority.

Tier B licenses only: “a strong evaluated throughput--generator-call Pareto
point on the frozen backbone.” If same-call superiority or the memory ablation
does not pass, do not claim that adaptive timing or recall caused the Pareto
result. If end-to-end timing does not pass Section 10, do not claim runtime
speedup.

### Tier C — No-Go for the current Context-Memory paper

The current paper route is No-Go if any of the following occurs:

- an integrity/audit failure cannot be resolved before fresh evaluation;
- context fails the bootstrap effectiveness condition;
- context fails the 1% exact-B25 non-inferiority condition;
- context averages more than six total calls or less than 75% call reduction;
- any fixed or causal sparse comparator point-dominates context;
- `context_no_reactivation_B25` point-dominates Context-Memory, which would
  invalidate recall as the focal method component;
- a required fresh arm is missing or deleted.

Tier C forbids rescuing the claim by changing G/S caps, thresholds, maps,
workload weights, NI margin, Holm family, or root vector. A different focal
method requires a new protocol and new roots. Existing fresh results may be
reported only as a transparent negative result.

## 9. Mandatory integrity audit

The complete 960-run artifact must demonstrate:

- identical map, agent count, starts, absolute task tape SHA/FNV, release
  projection, workload manifest, and guard suffix across paired arms;
- reset-observation SHA equality and a complete Python/C++ source manifest;
- zero online workload RNG draws and zero tape exhaustion;
- monotone task assignment/completion prefixes and reward sum equal to
  completed tasks;
- zero vertex collisions, edge swaps, invalid moves, endpoint mismatches,
  route-trace errors, and route-attribution errors;
- contiguous task, guidance-version, and route-build identities;
- exact generator/publication conservation, including zero generator charge
  for reactivation;
- exact G4/G5/B25 quotas, random-G5 schedule commitment, JS-G5 cap, and zero
  no-reactivation recalls;
- no future-tape access and a passing suffix-metamorphic sentinel;
- no task/planner/publication/method-order RNG coupling;
- no nondeterministic common-arm drift across fresh processes;
- all planner timeouts and method failures retained as outcomes;
- hashes for every raw and applied guidance graph and checkpoint identity.

Any audit failure makes the entire claim matrix invalid. A correctness fix
after fresh opening requires abandoning this root vector, freezing new code,
and deriving a new untouched vector; it may not be patched around by rerunning
only favorable cells.

## 10. Timing-only study

Timing begins only after Tier A or Tier B is determined. It cannot change the
throughput decision. Use old development roots `[17, 18, 19, 20, 21]`, the same
12 cells, and four methods:

- `exact_even_G4`;
- `exact_even_G5`;
- `context_memory_B25`;
- `exact_even_B25`.

This is 5 roots times 12 cells times 4 methods = **240 serial runs**. Run one
job at a time with exclusive CPU/GPU allocation, fixed CPU affinity, declared
warm-cache policy, and independently randomized/counterbalanced method order.
Record generator seconds, controller seconds, planner seconds, simulator
seconds, end-to-end wall time, peak memory, GPU utilization, and energy only if
the hardware exposes a reliable counter.

“At least 75% lower generator time” requires both the pooled and root-mean
reductions versus `exact_even_B25` to reach 75%. An end-to-end speedup claim is
allowed only if mean wall-time reduction is at least 5% and its root-cluster
95% CI lower bound is above zero. Otherwise report timing descriptively and
claim only fewer generator evaluations. Compare context overhead against both
G4 and G5; never infer throughput ranking from the timing-only roots.

## 11. Execution and stopping order

1. Implement only the frozen new method contracts and analyzers.
2. Run unit tests, source manifest, common-arm check, replay check, and
   suffix-metamorphic test.
3. Complete all 96 engineering-smoke runs. Do not perform inferential analysis.
4. If smoke passes, seal the final source/analyzer/launcher manifest.
5. Run all 960 fresh confirmation arms without interim effect inspection.
6. Run the frozen analyzer once and assign Tier A, B, or C mechanically.
7. Run the 240 timing-only arms only for Tier A/B.
8. Update the paper with the assigned tier and all negative/failed contrasts.

There is no additional low-level controller iteration in this protocol. The
locked seeds `1001..1030` and reserved sortation maps remain unopened; opening
them would require a separate explicit protocol and user decision after this
one-shot confirmation.
