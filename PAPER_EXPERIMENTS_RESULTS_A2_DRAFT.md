# Experiments and Results: A2 Same-Call Confirmation

> **Claim status (14 July 2026).** The A2 matrix passed every registered
> integrity audit, but the frozen analyzer assigned **Tier C: No-Go for the
> current Context-Memory paper** because the 1% non-inferiority test against
> `exact_even_B25` failed. This is not a SOTA result, does not establish that
> historical recall is beneficial, and does not license a runtime claim.
> Timing was not run because the protocol forbids it for Tier C. The evidence
> is restricted to a fresh, same-backbone OnlineGGO/GPIBT comparison.

## 4 Experimental Evaluation

### 4.1 Question and scope

We evaluate whether `context_memory_B25`, a context-selective guidance
publication controller with historical graph reactivation, provides a useful
throughput--generator-call trade-off on a frozen OnlineGGO-style CNN+GPIBT
backbone. The confirmatory question has two parts: (i) superiority to six
sparse-publication controls, and (ii) 1% non-inferiority to a dense 26-call
even schedule. All methods share the same simulator, learned generator,
checkpoint, planner, maps, starts, and exogenous task tapes; they differ only
in guidance-publication policy. This design compares controller policies on a
single backbone. It does not compare against external lifelong-MAPF systems
and therefore cannot support a global SOTA claim.

### 4.2 Simulator, scenarios, and matrix

Each episode has a 200-step warm-up followed by 2,000 scored steps. Decisions
occur every 20 steps, giving 100 scored windows, one mandatory bootstrap
generation, and 99 eligible post-bootstrap decisions. Tasks are supplied by
policy-independent absolute-release tapes with release interval 110 and four
guard tasks per agent. We cross three workloads (`stationary`, `abrupt`, and
`recurrent`) with four scenario cells:

| Scenario | Map | Density | Agents |
|---|---|---:|---:|
| `narrow_r020` | narrow | 0.20 | 218 |
| `narrow_r035` | narrow | 0.35 | 382 |
| `regular_r020` | regular | 0.20 | 255 |
| `regular_r035` | regular | 0.35 | 447 |

The A2 roots were frozen before any A2 run:
`[691817, 376110, 263001, 293231, 296805, 274330, 997942, 319782, 807287, 326454]`.
The complete design contains 8 methods x 10 roots x 3 workloads x 4 scenarios
= 960 runs, or 120 paired cells per method. The root seed, not the individual
cell, task, window, or agent, is the independent unit.

### 4.3 Comparators

| Method | Registered publication rule |
|---|---|
| `bootstrap_only` | One bootstrap call, then hold for the full episode. |
| `exact_even_G4` | Bootstrap plus four even post calls at decisions 25, 50, 75, and 99 (five calls total). |
| `exact_even_G5` | Bootstrap plus five even post calls at decisions 20, 40, 60, 80, and 99 (six total). |
| `random_G5` | Bootstrap plus five distinct, seed-keyed random post decisions (six total). |
| `js_cap_G5` | JS score/persistence policy capped at five post calls, with no catch-up or forced fill. |
| `context_no_reactivation_B25` | The focal policy with historical recall disabled; actual calls are outcomes, not call-matched. |
| `context_memory_B25` | Focal selective controller; may hold, generate, or reactivate a historical graph under B25 caps. |
| `exact_even_B25` | Bootstrap plus 25 evenly scheduled post calls (26 total). |

The focal method is empirically sparse but has a B25 ceiling; it is therefore
bracketed by fixed five- and six-call policies rather than evaluated under a
strict per-run equal-call budget.

### 4.4 Outcomes and inference

The primary outcome is the number of tasks completed during the fixed scored
horizon (equivalently throughput, since every horizon is 2,000 steps). Resource
use is measured by total generator calls; post-bootstrap generations,
effective switches, reactivations, and the complete call distribution are
secondary outcomes. Pareto dominance is defined on point estimates: method A
dominates B if A has no fewer mean tasks and no more mean calls, with at least
one strict inequality.

For candidate A and comparator B, the registered root-level effect is

$$
d_i(A,B)=\frac{1}{12}\sum_{c=1}^{12}
\frac{\mathrm{tasks}_{A,i,c}-\mathrm{tasks}_{B,i,c}}
     {\mathrm{tasks}_{B,i,c}}.
$$

The 12 cells receive equal weight. We report the mean of the ten root effects,
root win/tie/loss counts, and a 10,000-sample whole-root percentile bootstrap
95% CI (seed 20260715). Superiority uses an exact one-sided paired sign-flip
test over the ten roots, with Holm step-down correction across the six frozen
comparisons at family-wise alpha 0.05. The separate non-inferiority test versus
`exact_even_B25` uses margin -1.00% and requires all three registered
conditions: mean effect at least -0.50%, CI lower bound strictly above -1.00%,
and shifted one-sided exact p < 0.05. The reported CIs are estimation
intervals, not multiplicity-adjusted intervals.

### 4.5 Execution integrity and effect blinding

All 960 A2 runs completed. The audit verified paired exogenous inputs, source
and configuration hashes, budgets and schedules, safety invariants, and one
fresh process and canonical UUID per arm. It found 960/960 started and
completed ledger entries, 960 unique process instances, 960 unique run UUIDs,
zero planner timeouts, zero method failure/retry events, and zero selective or
timeout deletions.

An earlier A1 execution was abandoned effect-blind after its frozen launcher
rejected one recycled bare Linux PID, despite distinct process-start times and
UUIDs. No A1 outcome or method ranking was read; all A1 outcomes remain
ineligible. A2 changed only the process-identity audit and untouched root
vector, leaving treatments, estimands, inference, and tier rules unchanged.

## 5 Results

### 5.1 Primary superiority results

Positive effects favor `context_memory_B25`. Absolute task differences and
relative effects use the registered paired estimand; the relative effect is
not the ratio of the two grand means.

| Comparator | Mean task delta | Mean relative effect | 95% root CI | Root W/T/L | Raw p | Holm p |
|---|---:|---:|---:|---:|---:|---:|
| `bootstrap_only` | +154.30 | +3.72% | [+3.04%, +4.44%] | 10/0/0 | 0.00098 | 0.00586 |
| `exact_even_G4` | +86.20 | +2.04% | [+1.40%, +2.67%] | 10/0/0 | 0.00098 | 0.00586 |
| `exact_even_G5` | +8.65 | +0.17% | [-0.33%, +0.61%] | 7/0/3 | 0.25879 | 0.51758 |
| `random_G5` | +54.43 | +1.22% | [+0.14%, +2.52%] | 6/0/4 | 0.03906 | 0.11719 |
| `js_cap_G5` | +142.71 | +3.11% | [+2.32%, +3.93%] | 10/0/0 | 0.00098 | 0.00586 |
| `context_no_reactivation_B25` | -5.78 | -0.11% | [-0.48%, +0.21%] | 5/0/5 | 0.70801 | 0.70801 |

The focal controller is superior after Holm correction to `bootstrap_only`,
`exact_even_G4`, and `js_cap_G5`. It is not confirmatorily superior to
`exact_even_G5`, `random_G5`, or the no-reactivation ablation. In particular,
the recall contrast is slightly negative and evenly split across roots, so
these data do not show that historical recall adds throughput.

### 5.2 Generator calls and the empirical Pareto frontier

| Method | Mean tasks | Calls mean/median/P90/max | Calls <=5 / <=6 | Post generations | Switches | Reactivations | Frontier |
|---|---:|---:|---:|---:|---:|---:|:---:|
| `bootstrap_only` | 4417.03 | 1.00/1/1/1 | 100.0% / 100.0% | 0.00 | 0.00 | 0.00 | yes |
| `exact_even_G4` | 4485.12 | 5.00/5/5/5 | 100.0% / 100.0% | 4.00 | 4.00 | 0.00 | yes |
| `exact_even_G5` | 4562.68 | 6.00/6/6/6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 | no |
| `random_G5` | 4516.89 | 6.00/6/6/6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 | no |
| `js_cap_G5` | 4428.62 | 6.00/6/6/6 | 0.0% / 100.0% | 5.00 | 5.00 | 0.00 | no |
| `context_no_reactivation_B25` | 4577.10 | 6.98/6.5/10/13 | 36.7% / 50.0% | 5.98 | 5.98 | 0.00 | yes |
| `context_memory_B25` | 4571.32 | 5.47/5/8/12 | 60.8% / 78.3% | 4.47 | 6.12 | 1.65 | yes |
| `exact_even_B25` | 4598.92 | 26.00/26/26/26 | 0.0% / 0.0% | 25.00 | 25.00 | 0.00 | yes |

The point-estimate frontier is `bootstrap_only`, `exact_even_G4`,
`context_memory_B25`, `context_no_reactivation_B25`, and `exact_even_B25`.
At 5.47 mean calls, the focal method point-dominates all three six-call G5
controls and reduces calls by 78.97% relative to the 26-call reference.
However, 21.7% of focal runs exceed six calls and the maximum is 12. Frontier
membership is a descriptive point-estimate property, not a test of statistical
superiority or a runtime result.

### 5.3 The 1% non-inferiority condition fails

Against `exact_even_B25`, the focal method completes 27.59 fewer tasks on
average. Its registered mean relative effect is -0.40%, with a 95% root CI of
[-1.08%, +0.26%] and root W/T/L of 3/0/7. The mean satisfies the separate
-0.50% requirement, but the lower CI is not strictly above -1.00% and the
shifted exact one-sided p-value is 0.06836 rather than below 0.05. The frozen
non-inferiority test therefore fails. We cannot state that the focal method
retains throughput within 1% of the dense reference.

This single failure is sufficient to fail Tier B. The mechanical assignment is
therefore **Tier C: No-Go for the current Context-Memory paper**, even though
the audit, bootstrap comparison, mean-call ceiling, call reduction, empirical
frontier membership, and zero-deletion checks all pass.

### 5.4 Descriptive heterogeneity

The following are registered map- and workload-level mean effects, in percent;
positive values favor `context_memory_B25`. They are descriptive decompositions,
not separately multiplicity-controlled subgroup claims.

| Comparator | Narrow | Regular | Stationary | Abrupt | Recurrent |
|---|---:|---:|---:|---:|---:|
| `bootstrap_only` | +3.52 | +3.91 | +1.77 | +4.28 | +5.11 |
| `exact_even_G4` | +2.42 | +1.66 | -0.62 | +2.18 | +4.56 |
| `exact_even_G5` | +0.93 | -0.59 | -1.32 | +0.32 | +1.51 |
| `random_G5` | +0.67 | +1.76 | +0.29 | +0.85 | +2.52 |
| `js_cap_G5` | +3.74 | +2.48 | +0.11 | +5.65 | +3.57 |
| `context_no_reactivation_B25` | -0.06 | -0.17 | -0.06 | -0.06 | -0.22 |
| `exact_even_B25` | +0.43 | -1.23 | -0.42 | -0.68 | -0.10 |

The gain over bootstrap is directionally consistent across both maps and all
three workloads. In contrast, the exact-G5 comparison is negative on the
regular map and reaches -1.32% under the stationary workload; this fails the
registered cross-map and stationary-degradation checks. Relative to dense B25,
the effect changes from +0.43% on the narrow map to -1.23% on the regular map
and reaches -1.55% in `regular_r035`. The no-reactivation comparison is
negative in both maps and all workloads. These patterns suggest that the
observed efficiency is concentrated in avoiding unhelpful publications under
non-stationarity, but they do not identify historical recall as its cause.

### 5.5 Interpretation and DAI-positioned narrative

The strongest accurate reading is a **resource--throughput frontier result
with a failed near-exact claim**. On the frozen distributed-agent routing
backbone, context-selective publication yields +3.72% over reusing only the
bootstrap graph and uses 78.97% fewer generator calls than dense even updates.
It is an undominated empirical point and significantly exceeds three specific
comparators. At the same time, it does not establish 1% non-inferiority to the
dense reference, does not beat every six-call control, and does not validate
historical recall as the mechanism.

A defensible DAI submission can therefore emphasize an audited study of
resource-aware guidance publication: when learned guidance should be refreshed
in a distributed multi-agent system, what throughput is bought per generator
invocation, and where sparse adaptive control ceases to match dense updating.
The transparent NI failure and negative memory ablation are part of that
contribution. The manuscript must not describe this as SOTA, near-exact
throughput, a general victory over sparse scheduling, or proof that memory
improves performance.

### 5.6 Threats to validity

1. **External validity.** Evidence covers one frozen CNN+GPIBT backbone, two
   warehouse maps, two densities, three workloads, and ten roots. It is not a
   benchmark-wide comparison with external lifelong-MAPF algorithms.
2. **Statistical resolution.** There are ten independent root clusters, so
   exact sign-flip tests have only 1,024 assignments and the NI interval is
   relatively wide. The registered margin and alpha cannot be relaxed after
   observing the result.
3. **Budget comparability.** The focal B25 controller is sparse on average but
   is not hard-capped at G5 per run; calls range up to 12. Comparisons to G4/G5
   therefore use actual-call bracketing, not strict equal hard budgets.
4. **Mechanism identification.** The no-reactivation ablation has slightly
   higher mean tasks and higher mean calls. The recall contrast is non-significant,
   so efficiency cannot be causally attributed to historical memory.
5. **Pareto uncertainty.** The frontier uses grand point estimates. It does
   not imply pairwise statistical superiority or uncertainty-aware dominance.
6. **No timing evidence.** Generator calls are a logical resource count, not
   measured latency, energy, or end-to-end runtime. The registered protocol
   forbids the timing study after Tier C, so no speedup claim is allowed.
7. **Post-validation framing.** The Pareto question was formulated after
   validation-v2, although A2 used untouched roots and frozen rules. The 1%
   NI margin was retained from the earlier protocol and is disclosed rather
   than reselected.

## Reproducibility provenance

- A2 protocol: `EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A2.md`, SHA-256
  `c1caaf9532ac728b19761d0eab60628d8e32e4d3a101512b51fa0a5abeebf9dd`.
- Frozen A2 config: `configs/same_call_confirmation_a2.json`, SHA-256
  `e0763c409c900bbc21e9b69fff5e978261a89cba8ad883d16ef705d012c9d96f`.
- Machine-readable analysis: `reports/same_call_confirmation_a2_analysis.json`,
  SHA-256 `9257a16f8fadb2135bcc434cb731abda9d2ba452b85287bff045e667ae37a71e`.
- Human-readable analysis: `reports/same_call_confirmation_a2_analysis.md`,
  SHA-256 `2358e8a3c51d7b14b6806d85eb72a9e172876641973143eac7f219ed6c0c495e`.
