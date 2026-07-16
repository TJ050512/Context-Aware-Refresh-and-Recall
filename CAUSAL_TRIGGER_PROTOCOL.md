# Gate 0 causal publication-trigger protocol

This is a diagnostic protocol. The current `next_route_flow` candidate
generator consumes true Kiva distribution weights, and the frozen trigger is
only queried at a true distribution-update boundary. Results from this stage
cannot be described as a deployable trigger, OnlineGGO, or SOTA evidence.

## Why single-shift episode totals are not labels

`shiftmask_100 - never`, `shiftmask_010 - never`, and
`shiftmask_001 - never` identify effects only on the reuse-only prefix. Their
whole-episode totals also mix the target action with later workload phases.
They cannot label states produced by earlier publications.

For three shifts, run the complete eight-trajectory tree for every seed:

```text
never (= 000), 001, 010, 011, 100, 101, 110, 111
```

The seven conditional contrasts are:

```text
000 <-> 100
000 <-> 010    100 <-> 110
000 <-> 001    010 <-> 011    100 <-> 101    110 <-> 111
```

Each pair must have byte-identical pre-action feature and simulator-state
fingerprints. Its label is the completed-task difference from that shift to
the next shift, with both arms using a reuse-only suffix. In simulator trace
notation this is `(shift_t, next_shift_t]`; it corresponds to the registered
decision interval `[shift_t, next_shift_t)` because the distribution update at
the right boundary occurs after that timestep's completions.

## Frozen split

- Development/training: seeds 20--26, 8 trajectories per seed, 49 labels
  total. Seeds 17--19 were already inspected and remain diagnostic evidence;
  this trigger artifact deliberately does not train on them.
- Validation/evaluation: seeds 101--110; no refitting, threshold selection, or
  feature selection is permitted.
- Locked test: seeds 1001--1030 remain sealed for the one-shot confirmatory
  protocol. This diagnostic pipeline must not run or inspect them.
- Seeds 30--39 are not a test split and are not used by this registered
  artifact.
- Ridge regularization is selected only by leave-one-development-seed-out CV.
- The two frozen diagnostics are the ridge mean at zero and
  `mean - beta * sigma * sqrt(x^T A^-1 x)` at zero.

True distribution weights, distribution divergence, shift index, and episode
progress are retained only in pairing audit metadata and are rejected if
listed as model features. Candidate/current guidance drift is computed before
the candidate graph is applied; preview purity and the exact flattened action
hash are tested.

## Commands

Inspect the frozen plan without running the simulator:

```bash
python scripts/gate0_causal_trigger_pipeline.py plan \
  --config configs/gate0_causal_trigger_v1.json
```

Generate the development artifact on the official server with the seeds and
methods emitted by that plan. Then build labels and freeze the model:

```bash
python scripts/gate0_causal_trigger_pipeline.py dataset \
  --config configs/gate0_causal_trigger_v1.json \
  --artifacts results/official_gate0/causal/dev_shiftmask.json \
  --output results/official_gate0/causal/dev_prefix_labels.json

python scripts/gate0_causal_trigger_pipeline.py train \
  --config configs/gate0_causal_trigger_v1.json \
  --dataset results/official_gate0/causal/dev_prefix_labels.json \
  --output results/official_gate0/causal/frozen_ridge_trigger.json

python scripts/gate0_causal_trigger_pipeline.py verify-evaluation \
  --config configs/gate0_causal_trigger_v1.json \
  --model results/official_gate0/causal/frozen_ridge_trigger.json
```

Only after verification should the official runner evaluate `never`,
`oracle_boundary_ridge`, `oracle_boundary_lcb`, and `oracle_shift` on the
validation/evaluation seeds 101--110 with `--trigger-model` pointing to the
frozen artifact. Do not run this diagnostic on the sealed 1001--1030 block.
