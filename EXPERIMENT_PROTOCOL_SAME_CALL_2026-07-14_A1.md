# Frozen same-call confirmation protocol — Amendment A1

Date: 2026-07-14  
Status: **frozen after engineering-only preflight and before any fresh-root run**  
Amendment class: evidence-provenance and execution-environment correction only  
Predecessor: `EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md`  
Predecessor SHA-256:
`9e3740d240525100183eb54ddbfd81e475e8f9680002ed34a2255568ea878a41`

## A1.1 Scope, timing, and precedence

This document is a versioned, effect-blind amendment to the predecessor. The
predecessor remains immutable. All of its provisions remain in force except
where this document explicitly replaces the cross-instance common-arm output
gate in Sections 5, 9, and 11, and strengthens the host rule in Sections 6.2
and 11.

At the instant A1 was frozen:

```yaml
amendment_id: dai-same-call-confirmatory-2026-07-14-A1
fresh_root_runs_observed: 0
fresh_effect_estimates_computed: 0
fresh_method_rankings_inspected: 0
development_root_used_for_engineering_only: 17
```

The amendment was triggered solely by a determinism audit on contaminated
development root 17. No member of the frozen fresh-root vector had been run,
opened, partially inspected, or used to formulate A1. The engineering outputs
that motivated A1 remain ineligible for treatment-effect estimation, method
selection, threshold selection, stopping, or a Go decision.

## A1.2 Scientific design is unchanged

A1 changes neither the scientific question nor any treatment or analysis
choice. The following predecessor commitments remain exactly frozen:

- the eight methods, in the same family and with the same contracts;
- the four scenarios, three workloads, warm-up, horizon, decision window,
  release interval, guard suffix, checkpoint, maps, densities, and simulator;
- the ten fresh roots
  `[767369, 695428, 323681, 904171, 446020, 434435, 488565, 514527, 544573,
  838809]`;
- all 960 mandatory fresh arms and fresh-process-per-arm execution;
- the root-level estimands, 12-cell equal weighting, bootstrap seed and sample
  count, exact sign-flip tests, Holm family, 1% non-inferiority margin, outcome
  tiers, stopping rules, and reporting requirements;
- the prohibition on post-freeze tuning, arm deletion, comparator replacement,
  interim effect analysis, or rescuing a failed tier with a changed analysis.

No behavior-code correction is authorized by this amendment. A behavior or
analysis-code change still invokes the predecessor's invalidation rule.

## A1.3 Immutable protocol and runner lineage

The A1 implementation manifest must bind both the predecessor and this A1
file by exact SHA-256. This file's digest is recorded externally after the file
is sealed; it is intentionally not self-embedded. The source lineage used by
the compatibility gate is:

| Role | Artifact | SHA-256 |
|---|---|---|
| predecessor protocol | `EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md` | `9e3740d240525100183eb54ddbfd81e475e8f9680002ed34a2255568ea878a41` |
| archived legacy method source | `src/dai_lmapf/claim_runner.py` | `d9bf61bfa2f86881084b2b1abc19aa0f7483206fa58dcdc88c0b086099d03c2e` |
| archived legacy runner | `scripts/run_claim_aware_budgeted_validation.py` | `694c6af03421e653b7d273d6e5f9da3dd6d1ec349f9120b8efe06bf466b33d50` |
| versioned same-call method source | `src/dai_lmapf/same_call_claim_runner.py` | `53fe48d7fda7638dbd79423d01f4f07de5e13a04938d9a1516855347413ef495` |
| versioned same-call runner | `scripts/run_same_call_confirmation_v1.py` | `9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538` |

The legacy-current replay must execute the exact legacy source pair in this
table. The A1 smoke and confirmation must execute the exact same-call source
pair. A source mismatch, unrecorded wrapper, or mutable import outside the
sealed source manifest is a hard preflight failure.

## A1.4 Engineering finding and corrected evidence boundary

The original cross-instance audit compared archived outputs from a previous
AutoDL instance with outputs on the current instance. Across the 36 common
arms—three methods (`bootstrap_only`, `context_memory_B25`,
`exact_even_B25`) times four scenarios times three workloads—the archived and
current runs retained the same frozen source and causal inputs, but their CNN
bootstrap guidance differed numerically and their downstream trajectories
diverged. Archived-versus-current output equality was 0/36. On the current
host, however, executing the exact frozen legacy runner and the versioned
same-call runner produced 36/36 bitwise-identical common-arm causal outputs.

This isolates the observed archive mismatch to cross-instance numerical
environment drift rather than a semantic change introduced by the same-call
runner. It also shows that a cross-instance bitwise-output requirement is not
a valid compatibility test for this CPU/BLAS-sensitive CNN path. A1 therefore
separates two evidence roles.

### A1.4.1 Cross-instance archive: input/source identity is a hard gate

For every one of the 36 archived common arms, the A1 auditor must verify exact
identity of every available pre-treatment determinant, including at minimum:

- legacy source snapshot hashes, simulator-interface source hashes, checkpoint
  file and float32-parameter hashes, simulator binary hash, and map hash;
- method, root, scenario, agent count, workload, warm-up, horizon, decision
  window, release interval, guard suffix, sigma, and all controller constants;
- start locations, task-tape content SHA/FNV and manifest identity, workload
  manifest, release projection, reset causal fingerprint, and distribution
  update fingerprint.

Missing identity evidence or any mismatch is a hard failure. The audit must
emit field-level counts and mismatches, not only a single Boolean.

Cross-instance output comparison is retained as a mandatory, explicitly
non-blocking diagnostic. It must report the number of equal and unequal arms
and the first divergent causal field or stage. Guidance hashes, trajectories,
completed-task counts, and other outputs are **not** required to match across
instances. Their equality or inequality cannot pass or fail preflight.

Archived outputs are never effect evidence for the fresh confirmation. They
must not be pooled with, substituted for, normalized against, or otherwise
used in fresh treatment effects, ranks, confidence intervals, p-values, tier
assignment, method selection, or claims. The observed 0/36 cross-instance
output match is reported transparently as an engineering diagnostic only.

### A1.4.2 Current-host legacy-versus-new replay: 36/36 is a hard gate

On the exact host reserved for the fresh matrix, execute both the frozen
legacy source pair and the frozen same-call source pair for all 36 common arms.
The two runners must receive identical causal inputs and the environment
attestation in Section A1.5. Every arm must run in a fresh OS process.

All 36 pairs must be bitwise identical over the complete deterministic causal
projection, including completed-task outcome and trajectory, task/release/reset
identities, raw and applied guidance hashes, publication decisions and
timeline, action/window timeline, safety and invariant payloads, and all
generator/publication conservation fields. The only excluded fields are
wall-clock/timing measurements and an auditor-maintained allowlist of purely
execution metadata: process identifiers, run UUIDs, process-start timestamps,
log paths, attempt ordering, and method-order metadata. The allowlist must be
emitted in the audit report; no causal or outcome field may be added to it.

The required result is exactly 36/36 matching pairs. One mismatch is an
engineering stop. It must not be waived because the archived run happened to
match either side.

## A1.5 Frozen host and environment attestation

Before the A1 replay gates, create an append-only environment attestation and
seal its SHA-256 in the A1 implementation manifest. At minimum it records:

- a stable host-instance fingerprint composed of hostname, machine identity,
  CPU model/count, and ordered GPU model/UUID inventory;
- OS image, kernel, architecture, glibc, compiler, libstdc++, and relevant
  native-library versions;
- Python, PyTorch, NumPy, CUDA runtime, NVIDIA driver, cuDNN, and BLAS backend
  versions and configuration;
- selected GPU/device policy, determinism flags, RNG controls, and
  `torch.get_num_threads()` / `torch.get_num_interop_threads()`;
- exact values of `OMP_NUM_THREADS`, `MKL_NUM_THREADS`,
  `OPENBLAS_NUM_THREADS`, `NUMEXPR_NUM_THREADS`, and
  `VECLIB_MAXIMUM_THREADS`, all of which remain `1`;
- hashes for all frozen source files, launchers, analyzers, protocol files,
  checkpoint identities, simulator binary, and maps.

The legacy-current gate, repeat gate, suffix gate, A1 engineering smoke, and
all fresh arms must reference the same attestation digest. A fresh process may
not silently inherit a different thread, device, library, or determinism
configuration.

All 960 fresh arms must execute on the **same attested physical/cloud host
instance** used for the passing current-host replay gates. Results from two
hosts may not be combined, even when both hosts independently pass preflight.
If the host changes before any fresh arm, create a new attestation and rerun
the complete A1 preflight. If the host changes after a fresh arm is opened,
stop: A1 does not authorize mixing hosts or silently restarting the matrix on
a replacement instance.

## A1.6 Repeat and future-suffix hard gates

The current host must also pass both of the following before any fresh root is
opened.

1. **Independent repeat.** Run two independent fresh-process repeats of the
   declared representative replay arms. Their complete causal replay
   projections must be bitwise identical, excluding only the same timing and
   execution-metadata allowlist used in Section A1.4.2. The report must list
   compared arms, compared fields, exclusions, and equality counts.
2. **Future-suffix metamorphic test.** Run the declared base and mutated-suffix
   pair with an identical prefix and a task/release mutation strictly after
   the frozen cutoff. The full tape hashes must differ, proving the mutation
   was real. Every observation, feature, score, decision, operation, raw and
   applied guidance hash, action, reward, completion prefix, and window record
   causally available at or before the cutoff must remain bitwise identical.
   Any prefix difference is a hard failure.

These gates test same-host repeatability and non-anticipation. They cannot be
replaced by cross-instance archive agreement.

## A1.7 Versioned A1 smoke and audit artifacts

After sealing the A1 protocol, source lineage, and environment attestation,
run a versioned 96-arm engineering smoke on root 17 under A1. The launcher and
all reports, ledgers, logs, replay artifacts, and smoke outputs must use new
append-only paths and refuse overwrite. The A1 audit report must separately
record:

1. archive source/input identity hard-gate result;
2. archive output-drift non-blocking diagnostic;
3. current-host legacy-versus-new 36/36 hard-gate result;
4. independent-repeat hard-gate result;
5. future-suffix hard-gate result;
6. environment/host attestation result;
7. all original schedule, budget, safety, RNG-isolation, ledger, and source
   manifest gates.

Only an A1 report with all hard gates passing may be sealed into the final
confirmation config. The predecessor's failed cross-instance-output report is
preserved and must never be overwritten or relabeled as passing.

## A1.8 Amended execution order

The predecessor's Section 11 is amended only as follows:

1. Seal A1 while `fresh_root_runs_observed=0`; record both protocol hashes in
   a new versioned implementation manifest.
2. Capture and seal the target-host environment attestation.
3. Run the versioned A1 unit/source checks and 96-arm engineering smoke.
4. Run the archive source/input identity gate and retain archive output drift
   as a non-blocking diagnostic.
5. On that same host, run the 36-arm legacy-versus-new gate and require 36/36
   bitwise equality.
6. On that same host, pass the independent-repeat and future-suffix hard gates.
7. Seal the passing A1 audit and final source/analyzer/launcher/config hashes.
8. On that same attested host, run all 960 fresh arms without interim effect,
   rank, or p-value inspection.
9. Run the unchanged frozen analyzer once and assign Tier A, B, or C
   mechanically; run timing only if the unchanged Tier A/B rule permits it.

Nothing in A1 converts development, archive, smoke, replay, or diagnostic
outputs into scientific effect evidence. The only treatment-effect evidence
for this protocol remains the untouched 960-arm fresh matrix.
