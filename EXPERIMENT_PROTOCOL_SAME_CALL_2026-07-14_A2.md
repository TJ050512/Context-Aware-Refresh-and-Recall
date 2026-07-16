# Frozen same-call confirmation protocol — Amendment A2

Date: 2026-07-14  
Status: **frozen after an effect-blind A1 execution-audit failure and before any A2 fresh-root run**  
Amendment class: process-instance identity correction and replacement-root restart only  
Predecessors: `EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md` and
`EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14_A1.md`

## A2.1 Trigger, blindness, and disposition of A1

The A1 matrix completed all 960 mandatory arms on its attested host, but its
frozen post-run launcher rejected the matrix because one integer Linux PID was
observed in two scenario artifacts. Before this amendment was written, the
only inspected A1 fields were execution metadata, file hashes, ledger
identities, and completion counts. No completed-task outcome, treatment
effect, method rank, confidence interval, p-value, or outcome tier was read or
computed.

The effect-blind incident record is
`reports/same_call_a1_effect_blind_execution_failure.json`, SHA-256
`6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48`.
It seals all A1 artifacts and ledgers and records:

- 960 completed arms;
- 959 distinct bare PID integers;
- 960 distinct `(host, PID, process_start_ns)` process instances;
- 960 distinct run UUIDs; and
- 960/960 append-only ledger-to-artifact bindings.

The repeated bare PID was `108072`, with different process-start timestamps
and UUIDs. This is legal Linux PID recycling, not reuse of one live process for
two arms. Nevertheless, A1 required its frozen analyzer to remain unchanged
after fresh roots were opened. A1 is therefore abandoned before effect
analysis. Its outcomes are permanently ineligible for estimation, ranking,
method selection, threshold selection, stopping, or paper claims.

At A2 freeze:

```yaml
a2_fresh_root_runs_observed: 0
a1_effect_estimates_computed: 0
a1_method_rankings_inspected: 0
a1_outcome_tier_assigned: false
```

## A2.2 Scientific design remains unchanged

A2 changes no behavior, treatment, comparator, scenario, workload, map,
checkpoint, simulator, budget, estimand, hypothesis, multiplicity correction,
bootstrap procedure, non-inferiority margin, outcome tier, or reporting rule.
All provisions of the predecessor and A1 remain in force except:

1. the A1 fresh-root vector is retired without analysis and replaced by the
   untouched A2 vector in Section A2.4; and
2. the erroneous bare-PID uniqueness predicate is replaced by the
   process-instance predicate in Section A2.3.

No behavior-code change is authorized. The eight frozen methods, four
scenarios, three workloads, 12-cell equal weighting, and all 960 mandatory
arms remain exactly as registered. Because the immutable v1 runner stores the
retired A1 root registry as a control-plane constant, A2 may add a thin
versioned entry-point which first verifies the exact v1 runner hash, replaces
only that root-registry constant with the vector in Section A2.4, updates the
non-causal split-provenance record to cite the A2 derivation in Section A2.4,
and then delegates to the unchanged v1 `main`. The wrapper may not override
any method, simulation, workload, budget, RNG, scientific output, or safety
logic. Tests must prove that roots outside the A2 vector are rejected, that
the emitted split provenance names the frozen A2 source/domain, and that the
frozen v1 module is the sole delegated implementation.

## A2.3 Correct fresh-process identity predicate

Each arm must still execute in a fresh OS process. For every retained arm the
runner records:

```text
process_instance = (execution_host,
                    execution_process_id,
                    execution_process_start_ns)
```

The A2 hard gates are:

- exactly 960 unique process-instance tuples;
- exactly 960 unique canonical run UUIDs;
- child PID differs from its runner parent PID for every arm;
- the append-only started/completed ledger covers every frozen arm exactly
  once and binds the same host, PID, process-start timestamp, UUID, and
  canonical run hash; and
- all arms reference the same A1 target-host/environment attestation.

Bare PID integers are recyclable handles and are not globally unique process
identities. Their distinct count and every reuse group must be reported as an
execution diagnostic, but bare-PID reuse cannot pass or fail the matrix when
the process-instance, UUID, and ledger gates above pass. Repetition of a full
process-instance tuple or UUID remains a hard failure.

The versioned A2 control-plane entry-point, launcher, analyzer, tests,
implementation manifest, and final config must be frozen before opening any
A2 root. Apart from the registered root-vector replacement, this identity
predicate, and diagnostic field names, the A2 analyzer must be logic-equivalent
to the frozen v1 analyzer over all other integrity checks, outcomes, estimands,
inference, tiers, and reporting.

## A2.4 Deterministic untouched replacement roots

The replacement vector is derived only from the effect-blind A1 incident
record, before any A2 run:

```text
source = 6b813b41e5d269fd26cef8d15b6cdb444ee8c01539254072f85f715b4378fa48
domain = dai-same-call-confirmatory-a2-pid-reuse-correction
s_i = 100000 + (int(SHA256(source|domain|i)[0:16], 16) mod 900000)
```

The authoritative A2 vector is:

```text
[691817, 376110, 263001, 293231, 296805,
 274330, 997942, 319782, 807287, 326454]
```

Repository search at freeze found no prior use of these values as root seeds.
Only these roots are permitted for A2. Once any one is opened, all 960 arms are
mandatory and no result may be deleted, replaced, or selectively rerun.

## A2.5 Reused and repeated engineering gates

Because A2 changes no behavior source, simulator, data, map, checkpoint, or
environment, the passing A1 same-host legacy/new replay, repeatability test,
future-suffix test, 96-arm smoke, environment attestation, and source/input
provenance audit remain applicable by exact hash. Before any A2 root opens:

1. verify the host fingerprint and environment-attestation digest are still
   identical to A1;
2. verify every frozen behavior/source/data hash is identical to A1;
3. run the complete unit/source gate, including all A2 process-identity tests;
4. seal an A2 preflight report that references the passing A1 evidence and
   explicitly records zero A2 fresh runs; and
5. seal the A2 protocol, launcher, analyzer, tests, implementation manifest,
   final config, and their SHA-256 values.

A host or behavior-source change invalidates reuse of the A1 engineering
gates and requires a new attestation and full preflight.

## A2.6 Execution, one-shot analysis, and timing

Run 8 methods times 10 A2 roots times 3 workloads times 4 scenarios: exactly
960 arms, one fresh process per arm, on the single attested A1/A2 host. Use
new append-only `a2` result, ledger, log, and report paths; refuse overwrite.
Do not inspect outcomes, effects, ranks, or provisional p-values while the
matrix is incomplete.

After all integrity gates pass, execute the frozen A2 analyzer exactly once
and assign Tier A, B, or C mechanically under the unchanged predecessor
rules. Timing remains forbidden for Tier C. For Tier A or B, the unchanged
240-run serial timing-only protocol in predecessor Section 10 applies; timing
cannot alter throughput conclusions.

No A1 outcome may be pooled with, compared against, substituted for, or used
to interpret the A2 confirmation.
