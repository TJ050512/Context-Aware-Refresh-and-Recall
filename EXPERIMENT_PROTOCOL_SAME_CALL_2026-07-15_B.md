# Confirmatory Experiment B protocol — independent high-power replication

Date: 2026-07-15  
Status: **pre-specified before any Experiment B root is opened; the executable
implementation becomes frozen when the B freeze manifest is sealed**  
Predecessors: `EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md`,
`EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A1.md`, and
`EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A2.md`

This is an internal, content-hashed protocol freeze. It is not described as a
public preregistration. Experiment B is a standalone replication. Its outcomes
will not be pooled with A1 or A2 for the primary analysis.

## B.1 Motivation and prior evidence

The A2 confirmation completed its 960 mandatory arms and passed its execution
audit. `context_memory_B25` (CARR) used substantially fewer generator calls
than `exact_even_B25`, but its pre-specified 1% non-inferiority test did not
pass: the A2 root-mean relative throughput effect was `-0.4009%`, with a 95%
whole-root bootstrap interval of `[-1.0834%, +0.2584%]` and one-sided
non-inferiority `p = 0.06836`. The point-estimate gate passed, while the
interval and p-value gates failed.

A2 used only ten independent root clusters, so its interval was imprecise.
That does **not** establish that low power was the cause of the failure. B is
designed to distinguish sampling imprecision from a genuine throughput cost by
repeating the same scientific comparison on 40 entirely new root clusters.
A2's failed test remains part of the paper's evidence record regardless of B's
result.

Planning simulations resampled A2's centered root residuals and indicated the
following approximate probability that all three non-inferiority gates pass at
`n = 40`: 99.7% at a true effect of 0.0%, 99.1% at -0.1%, 95.8% at -0.2%,
87.8% at -0.3%, 72.3% at -0.4%, and 49.9% at -0.5%. These are design
calculations, not evidence about B or the true effect. The probability declines
as the true effect becomes more negative because the `-0.5%` point-estimate
gate becomes binding; increased sample size cannot rescue a genuinely
unacceptable effect.

## B.2 Primary question and frozen scientific contract

The primary B question is:

> On the frozen same-backbone LMAPF benchmark, is CARR's equal-cell-weighted
> throughput non-inferior to dense `exact_even_B25` guidance within a 1%
> relative margin while meeting the retained `-0.5%` point-estimate gate?

B changes only the fresh root vector and its size. It changes no method,
comparator, map, scenario, workload, task generator, simulator, checkpoint,
policy, threshold, budget, estimand, weighting rule, margin, confidence
procedure, test, multiplicity family, or reporting rule.

The eight mandatory methods, in frozen order, are:

```text
bootstrap_only
exact_even_G4
exact_even_G5
random_G5
js_cap_G5
context_no_reactivation_B25
context_memory_B25
exact_even_B25
```

The three workloads are `stationary`, `abrupt`, and `recurrent`. The four
scenarios are:

| Scenario | Map | Agents |
|---|---|---:|
| `narrow_r020` | `warehouse_small_narrow_kiva.map` | 218 |
| `narrow_r035` | `warehouse_small_narrow_kiva.map` | 382 |
| `regular_r020` | `warehouse_small_kiva.map` | 255 |
| `regular_r035` | `warehouse_small_kiva.map` | 447 |

Every root therefore contributes 12 equally weighted cells per method.

## B.3 Deterministically derived fresh roots

The root vector was derived without inspecting any B outcome:

```text
source = 6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48
domain = dai-same-call-confirmatory-b-power-extension
s_i = 100000 + (int(SHA256("<source>|<domain>|<i>")[0:16], 16) mod 900000)
i = 0,...,39
```

The authoritative ordered vector is:

```text
[880565, 534821, 257578, 500976, 294860, 954705, 190142, 429853,
 398397, 560584, 175381, 598292, 461566, 526869, 115950, 130998,
 655067, 585455, 362413, 552654, 664860, 253714, 962860, 907962,
 381214, 583444, 371204, 934561, 491276, 541256, 523055, 713041,
 537643, 699809, 204011, 330180, 113743, 257704, 152753, 657283]
```

The derivation script must reproduce the predecessor A2 vector exactly before
accepting this vector. These roots have no overlap with the A1 or A2 vectors
and contain no duplicates. They may not be used for smoke, tuning, debugging,
interim inspection, or method selection.

## B.4 Matrix and frozen execution parameters

Run `8 methods x 40 roots x 3 workloads x 4 scenarios = 3840` mandatory arms.
Each scenario artifact contains 960 completed arms and has an append-only
attempt ledger containing 960 `started` and 960 `completed` events.

The scientific parameters are:

```text
warmup_time = 200
scored_horizon = 2000
decision_window = 20
release_interval_per_agent = 110
guard_suffix_tasks_per_agent = 4
sigma = 0.75
context_match_threshold = 0.05
context_recall_margin = 0.02
context_min_score = 0.10
context_min_gap = 6
context_maintenance_age = 25
context_maintenance_stability = 0.20
split = same_call_confirmation_v1
fresh_process_per_arm = true
```

`OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`,
`NUMEXPR_NUM_THREADS`, and `VECLIB_MAXIMUM_THREADS` are each fixed to 1.
Parallel job count is an execution-only setting chosen from the pre-B smoke;
it may affect elapsed time but not any scientific output or analysis.

Every arm runs in a fresh OS process. The immutable v1 runner is verified at
SHA-256
`9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538`.
A thin B wrapper may replace only the protected split's root registry and its
non-causal derivation metadata before delegating to that v1 runner. It may not
alter behavior, simulation, RNG, safety, audit, or output logic.

The frozen backbone includes:

- simulator binary SHA-256
  `9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5`;
- CNN checkpoint SHA-256
  `e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d`;
- checkpoint parameter-payload SHA-256
  `6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac`;
- narrow-map SHA-256
  `866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6`;
- regular-map SHA-256
  `0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd`.

The current remote environment is captured in a new B attestation. Before
formal execution, the launcher must require the live host and compatibility
projection to match that sealed attestation and must verify every frozen
artifact hash in the B config and implementation-freeze manifest.

## B.5 Engineering checks before formal roots

No B root may be opened until all of the following pass:

1. the B wrapper, analyzer, launcher, and their tests are complete;
2. the root derivation and non-overlap checks pass;
3. the target-host attestation and backbone hashes pass;
4. the protocol, config, scripts, tests, and attestation are sealed by SHA-256
   in the implementation-freeze manifest; and
5. an end-to-end smoke on historical development root(s), never on a B root,
   passes in an isolated output directory.

Smoke outcomes are engineering evidence only. They may not change a method,
threshold, sample size, hypothesis, or analysis rule. Any implementation change
after smoke requires a new manifest and a complete smoke rerun before B opens.

## B.6 Estimand and inference

For method `A`, comparator `C`, root `i`, and each of the 12 map-density-
workload cells `c`, define

```text
d_i(A,C) = (1/12) * sum_c [(tasks_A,i,c - tasks_C,i,c) / tasks_C,i,c].
```

The independent inference unit is the root. Report all 40 root effects, their
mean and median, root wins/ties/losses, absolute task difference, both map
effects, all three workload effects, and leave-one-root-out means. Intervals
use 10,000 whole-root percentile-bootstrap samples with RNG seed `20260715`.
No run-, task-, agent-, or window-level pseudo-replication is allowed.

### B.6.1 Primary standalone non-inferiority test

The primary contrast is `context_memory_B25` minus `exact_even_B25`. The
relative non-inferiority margin is `-1.00%`. For every root define
`z_i = d_i + 0.01` and apply the same one-sided exact paired sign-flip test as
in A2. Non-inferiority is confirmed only if all three frozen gates pass:

1. mean relative effect is at least `-0.50%`;
2. the 95% whole-root bootstrap interval lower bound is strictly above
   `-1.00%`; and
3. the one-sided non-inferiority p-value is below 0.05.

This singleton test is **not** included in the Holm family below. The three
gates, margin, and alpha cannot be changed after observing B.

### B.6.2 Replicated superiority family

The six predeclared one-sided superiority contrasts for
`context_memory_B25` are versus:

1. `bootstrap_only`;
2. `exact_even_G4`;
3. `exact_even_G5`;
4. `random_G5`;
5. `js_cap_G5`; and
6. `context_no_reactivation_B25`.

Each uses the exact paired sign-flip test over 40 root effects. Apply Holm
step-down correction across these six p-values at family-wise alpha 0.05.
Report raw and adjusted p-values. Bootstrap intervals are estimation
intervals and are not multiplicity-adjusted. These replicated contrasts and
the throughput--call Pareto summaries are secondary to B's standalone NI
question; they cannot be used to replace a failed primary test.

## B.7 Integrity gates and stopping rule

The formal launcher and analyzer must verify, at minimum:

- exactly four scenario artifacts, 960 arms per scenario, and 3840 arms total;
- exactly 1920 ledger events per scenario, with 960 starts and 960 completions;
- exactly 3840 unique `(host, PID, process_start_ns)` process instances and
  exactly 3840 canonical run UUIDs;
- exact agreement of every ledger identity and canonical run hash;
- complete pairing of maps, agent counts, starts, task tapes, release
  projections, workload manifests, and guard suffixes across methods;
- zero missing, duplicated, selectively deleted, or silently retried arms;
- every safety, route, RNG-isolation, future-access, budget, schedule,
  generator-conservation, checkpoint, source, and guidance-hash audit inherited
  from the frozen runner; and
- no overwrite of formal outputs.

Do not compute treatment effects, method ranks, intervals, or provisional
p-values while the matrix is incomplete. The frozen runner has no selective
resume contract. If infrastructure interruption prevents completion, seal and
quarantine the entire incomplete attempt with an effect-blind incident record,
then restart the complete 3840-arm matrix from empty formal paths under the
unchanged freeze; no completed-arm subset may be retained or selectively
rerun. A method failure, timeout, or safety failure is a scientific outcome,
not an infrastructure interruption, and cannot be deleted. A behavior or
analysis defect found after any B root opens invalidates this root vector; it
cannot be patched by either a partial or whole-matrix rerun.

After all 3840 arms and integrity gates pass, execute the content-hashed B
analyzer exactly once. B passes its primary objective if and only if all three
NI gates in B.6.1 pass. B fails otherwise. Report the result regardless of
direction. Do not tune and rerun after seeing the result.

## B.8 Reporting commitments

B is analyzed and reported as a standalone replication. A1 outcomes remain
ineligible because A1 was abandoned effect-blind. A2 is not pooled into B's
primary estimate, confidence interval, or p-value. The paper will disclose
A2's failed NI test alongside B's result, whether B passes or fails.

A B pass licenses only the scoped statement that CARR met the pre-specified 1%
non-inferiority criterion on the frozen benchmark in the 40-root replication,
together with accurately reported call savings and secondary contrasts. It
does not license a global SOTA, universal robustness, or runtime-speedup claim.
A B failure will be reported as failure to confirm non-inferiority and will not
be rescued by alternate margins, subsets, weights, roots, or analyses.

Any cadence-anchor experiment is secondary and descriptive, is run separately
from this 3840-arm matrix, and is never added to either the singleton NI test
or the six-comparison Holm family.
