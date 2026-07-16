# Same-Call Experiment B final decision memo

Date: 2026-07-15  
Status: final, after the single frozen analysis  
Primary evidence: `reports/same_call_confirmation_b_analysis.json`

## Executive decision

Experiment B is complete, internally valid, and suitable as the main empirical
evidence for a DAI paper. The experiment does **not** support the previously
registered strong claim that `context_memory_B25` is 1% non-inferior to the
26-call dense-refresh comparator. It does support a narrower and still useful
paper claim:

> Within one frozen OnlineGGO-style generator--GPIBT backbone, causal adaptive
> refresh produces a strong low-call throughput operating point: it uses about
> 79% fewer generator calls than dense refresh, lies on the empirical
> sample-mean Pareto frontier, and significantly outperforms all five frozen
> low-call comparators. The remaining throughput cost relative to
> dense refresh is measurable, and historical reactivation substitutes calls
> rather than improving throughput.

The mechanical outcome `TIER_C_NO_GO_CURRENT_CONTEXT_MEMORY_PAPER` is a no-go
for the original dense-equivalence/context-memory-success hypothesis. It is
not a no-go for a paired Pareto/resource-allocation paper.

## Frozen design and integrity

- 8 methods x 40 fresh root clusters x 3 workloads x 4 scenarios = 3,840 runs.
- Statistical independent unit: root seed, not an individual run.
- Each method has 480 paired cells and 40 independent root effects.
- All 3,840 runs completed; no failed, unfinished, retried, selectively deleted,
  or timeout-deleted cell was observed.
- All 3,840 run UUIDs and process instances are unique.
- Four attempt ledgers each contain exactly 960 starts and 960 completions.
- Pairing, task tapes, safety/invariants, budgets, schedules, source hashes,
  configuration hashes, and preflight evidence all passed.
- The effect-blind matrix audit passed before the frozen analyzer was run.
- A2 and B are not pooled. B is interpreted as a standalone fresh-root study.

## Primary dense-refresh comparison

Candidate: `context_memory_B25`  
Comparator: `exact_even_B25`

| Quantity | Experiment B result | Frozen gate | Result |
|---|---:|---:|---|
| Mean relative throughput effect | -0.8006% | at least -0.5% | Fail |
| 95% root-cluster CI | [-1.1935%, -0.3966%] | lower bound > -1% | Fail |
| Shifted one-sided exact p | 0.1693 | p < 0.05 | Fail |
| Mean absolute effect | -49.29 tasks | descriptive | -- |
| Root W/T/L | 11/0/29 | descriptive | -- |

All three registered non-inferiority gates fail. The data support saying that
CARR retains about 99.2% of dense-refresh throughput on the observed mean while
using far fewer generator calls. They do not support `non-inferior`,
`equivalent`, `near-lossless`, `within 1%`, or `performance preserved`.

## Low-call superiority family

All effects below are `context_memory_B25 - comparator`. P-values are from the
frozen exact root sign-flip family with Holm adjustment.

| Comparator | Mean delta | 95% root CI | Root W/T/L | Holm p | Decision |
|---|---:|---:|---:|---:|---|
| `bootstrap_only` | +4.4215% | [+3.7528%, +5.0721%] | 40/0/0 | 5.457e-12 | Significant |
| `exact_even_G4` | +2.1704% | [+1.7697%, +2.5888%] | 37/0/3 | 2.910e-11 | Significant |
| `exact_even_G5` | +0.7512% | [+0.3228%, +1.1842%] | 28/0/12 | 0.001532 | Significant |
| `random_G5` | +1.6860% | [+1.2653%, +2.1137%] | 36/0/4 | 3.372e-9 | Significant |
| `js_cap_G5` | +3.3593% | [+2.8454%, +3.8742%] | 39/0/1 | 9.095e-12 | Significant |
| `context_no_reactivation_B25` | -0.1080% | [-0.2573%, +0.0289%] | 18/0/22 | 0.9250 | Not significant |

Experiment B therefore establishes the main positive result more strongly than
A2: the adaptive method significantly outperforms all five frozen low-call
comparators, including the strongest six-call periodic
schedule, after familywise correction. It does not improve throughput over its
no-reactivation ablation.

## Calls and Pareto interpretation

- CARR mean/median/P90/max total generator calls: 5.458/5/8/10.
- Dense B25 calls: 26 for every run.
- Mean call reduction versus dense B25: 79.006%.
- 61.46% of CARR cells use at most 5 calls; 76.04% use at most 6 calls.
- CARR is not point-dominated in mean tasks--mean calls space.
- CARR point-dominates `exact_even_G5`, `random_G5`, and `js_cap_G5` on the
  registered sample means.
- The empirical frontier is `bootstrap_only`, `exact_even_G4`,
  `context_no_reactivation_B25`, `context_memory_B25`, and
  `exact_even_B25`.

Calls are a logical generator-use measure. A 79% reduction in calls must not be
reported as a 79% reduction in wall-clock time, GPU time, energy, or money.

## What historical reactivation contributes

Relative to `context_no_reactivation_B25`, CARR has -0.108% mean throughput
effect with a CI crossing zero and Holm p=0.925. CARR nevertheless reduces mean
total calls from 7.073 to 5.458 (about 22.8%) and post-bootstrap fresh
generations from 6.073 to 4.458 (about 26.6%). Thus recall is supported as a
descriptive call-substitution mechanism, not as a throughput-enhancing module.

## Paper decision and claim boundary

Recommended title:

> **When Should Global Guidance Be Refreshed? A Paired Pareto Study in Lifelong
> Multi-Agent Path Finding**

Use `pre-specified` or `frozen before execution` in the paper. Do not put
`Preregistered` in the title unless a public, independently verifiable
pre-execution registration exists.

Supported claims:

1. Refresh timing is an independent resource-allocation/control layer.
2. CARR significantly beats five frozen low-call comparators under the
   registered same-backbone setting.
3. CARR forms a non-dominated empirical mean throughput--call operating point.
4. It uses 79.01% fewer logical generator calls than dense B25, with an
   observed mean throughput effect of -0.80%.
5. The 1% non-inferiority hypothesis is not supported.
6. Recall primarily substitutes generation calls; it does not improve
   throughput in this evaluation.

Unsupported claims:

- global LMAPF SOTA or superiority to all solver families;
- equivalence/non-inferiority/near-losslessness versus dense refresh;
- memory or recall improves throughput;
- generator-call savings equal real runtime, energy, or monetary savings;
- 3,840 statistically independent observations;
- pooled A2+B estimates or post-result redefinition of the primary endpoint.

## Next action

No additional seeds with the unchanged method should be run to rescue the
failed non-inferiority claim. The paper can be written now with B as the main
standalone evidence and A2 disclosed as prior independent evidence without
pooling. Optional future strengthening should use a new protocol for measured
serial wall-clock cost or external validity across another map/backbone; it is
not required before drafting the current DAI paper.

## Evidence and archive identities

- Protocol SHA-256: `35de3d61030803e58517b361b90a60a042e6bc68290171ff974e16270a859d06`
- Config SHA-256: `44127caa81272e7fb15fcbf33a9d430222c869238cf87e35280f4c0f3fc4f112`
- Freeze manifest SHA-256: `d9348b600065a9bf368f7c797cb05a5cd85d1f23ae1c1b60737c8eeead657560`
- Environment attestation SHA-256: `a452e6e55c4d16689c16a6aace22b4a456fa3fc5acde678edbe7353afe2601bf`
- Integrity report SHA-256: `86cbb7ca0a7285f4ce099db3ae9862cd04853f49e575072ccb3fbe25ae10c02e`
- Analysis JSON SHA-256: `cceab3d62390d6a1acd1c5ee3e78ff2048851a20c448796f968f212db0fb428b`
- Analysis Markdown SHA-256: `c9042405856c4f53fbabd5395145ac9d53aa40edadda69e71b559ad60a3a16a4`
- Complete compressed archive SHA-256: `6acf741f7ac460458558f1892030b46072fa438e59f639196fee394a5d3658e0`
