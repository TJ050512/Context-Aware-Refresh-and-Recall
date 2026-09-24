# Context-Aware Refresh and Recall (CARR)

[![Conference](https://img.shields.io/badge/DAI%202026-Oral%20Presentation-blue)](#paper)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-yellow)](pyproject.toml)

**Official implementation of the DAI 2026 Oral paper:**

> **Budgeted Guidance Refresh Control: A Paired Throughput–Call Study in Lifelong Multi-Agent Path Finding**

🎉 **Accepted by DAI 2026 (Oral Presentation)**

<p align="center">
  <img src="assets/framework.png" width="850" alt="CARR framework: causal observation, hold/recall/generate control, and a frozen guidance generator and GPIBT planner">
</p>

<a id="paper"></a>

## 📄 Paper

**Authors:**

- Xiaoxiao Ma
- Quan Fang\*
- Xiankun Jiang

**Affiliation:** Beijing University of Posts and Telecommunications

**Conference:** The Eighth International Conference on Distributed Artificial Intelligence (DAI 2026)

**Status:** Accepted · Oral Presentation

\* Corresponding author: Quan Fang.

## Overview

CARR studies guidance lifecycle control in lifelong multi-agent path finding
(LMAPF). At each decision window, the controller chooses whether to **hold**
the active guidance, **recall** compatible historical guidance, or **generate**
new guidance. It operates on a frozen CNN guidance generator and a frozen
GPIBT planner, evaluating throughput–call trade-offs under paired workloads.

All evaluated policies share the same task tapes, generator, and planner;
only the guidance lifecycle controller changes. The frozen implementation
uses `reactivate` in operation names, configuration identifiers, and audit
fields for the action called **recall** in the paper.

## 🚀 Key Results

| Metric | Result |
|---|---:|
| Evaluation | 3,840 paired runs |
| Root clusters | 40 |
| CARR calls | 5.46 |
| Exact-B25 calls | 26 |
| Call reduction | 79.01% |
| Primary non-inferiority | Not established |

The result demonstrates a **throughput–call operating trade-off rather than
throughput parity**. The primary 1% non-inferiority objective against
Exact-B25 was not established. Logical generator calls are **not wall-clock
cost**, energy consumption, or measured resource savings. These results are
bounded to the frozen CNN+GPIBT backbone and evaluated workloads.

<details>
<summary>Detailed paired comparisons and inferential scope</summary>

| Comparison | Experiment B result | Interpretation |
|---|---:|---|
| CARR vs. Exact-B25 | -0.8006% paired mean relative effect; 95% whole-root CI [-1.1935%, -0.3966%]; shifted exact p = 0.1693 | All three non-inferiority gates failed |
| Logical generator calls | 5.458 for CARR vs. 26 for Exact-B25 | 79.006% fewer logical calls |
| CARR vs. five low-call comparators | +0.75% to +4.42%; all Holm-adjusted p < 0.002 | Supported paired throughput improvements in the evaluated setting |
| CARR vs. CARR-NoRecall | -0.108%; 95% CI [-0.257%, 0.029%]; Holm p = 0.925 | No supported throughput benefit from recall |
| Mean calls with/without recall | 5.458 vs. 7.073 | Recall descriptively substitutes cached guidance for some fresh generations |

The independent inferential unit is the **root cluster (n = 40)**, not an
individual run row.

</details>

## Repository Structure

```text
src/               CARR implementation
scripts/           Experiment and analysis scripts
configs/           Frozen experiment configurations
results/           Compact reproducible evidence
reports/           Statistical reports
assets/            Framework and result figures
tests/             Implementation and result regression tests
patches/           Pinned OnlineGGO modifications and upstream license
carr_rl_lite_exp/   Development-only and post-hoc appendix evidence
```

Start with the compact evidence in
[`results/same_call_confirmation_b/compact_runs.csv`](results/same_call_confirmation_b/compact_runs.csv)
and the analysis in [`scripts/analyze_compact_b.py`](scripts/analyze_compact_b.py).
The compact analysis needs only Python's standard library. A full simulator
rerun additionally requires the patched OnlineGGO backbone and trained
checkpoint described below.

## Reproduce Results

Run the following commands from the repository root.

### 1. Install dependencies

Use **Python 3.9 or later**. The compact analysis and summary verification
require only the standard library; no third-party installation is needed
for those steps. NumPy and PyTorch are optional and enable the frozen-CNN
checks and experiment components:

```bash
python3 -m pip install -e '.[experiment]'
```

Figure-generation dependencies are listed under [Regenerate figures](#regenerate-figures).

### 2. Run compact analysis

```bash
python3 scripts/analyze_compact_b.py \
  --output reproduced/compact_b_analysis.json --force
# Optional byte-for-byte check on macOS/Linux:
cmp reproduced/compact_b_analysis.json reports/compact_b_analysis.json
```

The command validates the complete matrix, pairing fingerprints, safety
flags, and generator/switch conservation before recomputing method summaries,
call distributions, paired root-level effects, bootstrap intervals, exact
sign-flip tests, Holm correction, all three non-inferiority gates, and the
sample-mean Pareto frontier.

The post-hoc root-bootstrap report is independently reproducible:

```bash
python3 scripts/analyze_posthoc_review_sensitivity.py \
  --csv results/same_call_confirmation_b/compact_runs.csv \
  --output reproduced/posthoc_review_sensitivity_2026-08-03.json \
  --seed 20260803 --bootstrap-samples 10000
cmp reproduced/posthoc_review_sensitivity_2026-08-03.json \
  reports/posthoc_review_sensitivity_2026-08-03.json
```

### 3. Verify hashes

| Artifact | SHA-256 |
|---|---|
| `results/same_call_confirmation_b/compact_runs.csv` | `223951f30d7ca4f142a5b945cdc1e53ed59ac40ce7d0a19e949f3f4f3bbe626a` |
| `reports/compact_b_analysis.json` | `b675db23a294d2f1becae7f6eb5e231004e883c6f737e131069cc75df9cb22b0` |
| `scripts/analyze_posthoc_review_sensitivity.py` | `854eb256f76c4ad71c020d0807ec04b05a11461c4d1184665abe02338507e67a` |
| `reports/posthoc_review_sensitivity_2026-08-03.json` | `77845872984724a9f8f73e3537e584a17d41aab48b543f6fc7b3161e5e7cf0ea` |

Print the hashes with Python and compare them with the values above:

```bash
python3 - <<'PYHASH'
import hashlib
from pathlib import Path

for name in (
    "results/same_call_confirmation_b/compact_runs.csv",
    "reports/compact_b_analysis.json",
    "scripts/analyze_posthoc_review_sensitivity.py",
    "reports/posthoc_review_sensitivity_2026-08-03.json",
):
    print(hashlib.sha256(Path(name).read_bytes()).hexdigest(), name)
PYHASH
```

Additional appendix checks and their hashes are validated against
`carr_rl_lite_exp/ARTIFACT_SHA256.json`:

```bash
python3 carr_rl_lite_exp/scripts/verify_public_summaries.py
```

### 4. Run tests

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m unittest discover -s tests -v
```

The suite regenerates the development runner from the frozen v1 runner,
checks compact exploratory summaries against their public CSVs, reproduces
the post-hoc report byte for byte, and checks committed results for
machine-specific paths and host information.

The compact-result regression test can also be run separately:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m unittest -v tests.test_compact_b_artifact
```

## Regenerate figures

```bash
python3 -m pip install -e '.[figures]'
python3 scripts/make_result_figures.py
python3 scripts/make_framework_figure.py
```

Generated PDFs are written to `reproduced/figures/` and are not tracked.
The PNG files under `assets/` are the figure previews included in this
repository.

## Full Experiment

The modified backbone is reconstructed from a pinned upstream OnlineGGO
revision and the patch in `patches/`:

```bash
bash scripts/setup_onlineggo.sh
```

The full experiment entry point is:

```bash
python3 scripts/run_same_call_confirmation_b.py --help
```

A full 3,840-run rerun additionally requires the trained CNN checkpoint and a
native OnlineGGO build. Those large machine-dependent artifacts are not
included here; the portable public design is in
`configs/experiment_b_public.json`. The included compact table and analysis
are sufficient to audit every numerical result reported above.

For portability, the bundled base runner records the public JSON configuration
in its post-run source manifest instead of the retired internal protocol file.
This manifest-path substitution is non-causal: it is not read by the
simulation, workload, guidance lifecycle controller, or random-number streams.

In the public configuration, `standalone_replication` means that Experiment B
is analyzed independently rather than pooled with earlier experiments. It
does not mean that the external checkpoint and native simulator build are
bundled in this repository.

<details>
<summary>Core execution path</summary>

The implementation follows this execution path:

```text
absolute workload tape
  -> OnlineGGO environment adapter
  -> causal observation and invariants
  -> CARR guidance lifecycle controller
       -> hold
       -> recall cached guidance
       -> generate guidance with the frozen CNN
  -> GPIBT planner
  -> completed-task count
```

The corresponding files are
`absolute_workload.py`, `online_ggo_adapter.py`, `invariants.py`,
`publication_policy.py`, `frozen_cnn_generator.py`, and
`same_call_claim_runner.py`.

</details>

## Experimental Evidence

<details>
<summary>Paired experimental design</summary>

Experiment B is a fully paired matrix:

| Dimension | Value |
|---|---|
| Policies | 8 |
| Independent root clusters | 40 |
| Scenarios | 4 |
| Workloads | stationary, abrupt, recurrent |
| Total runs | 8 × 40 × 4 × 3 = 3,840 |
| Runs per policy | 480 |
| Warm-up / scored horizon | 200 / 2,000 timesteps |
| Decision window | 20 timesteps |

| Scenario | Map | Density | Agents |
|---|---|---:|---:|
| `narrow_r020` | narrow warehouse | 0.20 | 218 |
| `narrow_r035` | narrow warehouse | 0.35 | 382 |
| `regular_r020` | regular warehouse | 0.20 | 255 |
| `regular_r035` | regular warehouse | 0.35 | 447 |

Every scenario–root–workload cell uses the same task-tape, release-projection,
and reset-causal fingerprints across all eight methods. Intervals use 10,000
whole-root bootstrap samples. Superiority tests use exact root-level sign
flips with Holm correction across six comparisons. The primary
non-inferiority test is outside that multiplicity family.

</details>

<details>
<summary>Complete operating points and result figures</summary>

Boldface identifies the proposed method; it does not indicate the best value in
each column.

| Code name | Display label | Mean completed tasks | Mean logical calls | Median / P90 / max calls |
|---|---|---:|---:|---:|
| `bootstrap_only` | Bootstrap | 4,355.08 | 1.000 | 1 / 1 / 1 |
| `exact_even_G4` | Exact-G4 | 4,451.10 | 5.000 | 5 / 5 / 5 |
| `exact_even_G5` | Exact-G5 | 4,505.35 | 6.000 | 6 / 6 / 6 |
| `random_G5` | Random-G5 | 4,465.94 | 6.000 | 6 / 6 / 6 |
| `js_cap_G5` | JS-G5 | 4,391.32 | 6.000 | 6 / 6 / 6 |
| `exact_even_B25` | Exact-B25 | 4,588.90 | 26.000 | 26 / 26 / 26 |
| `context_no_reactivation_B25` | CARR-NoRecall | 4,544.06 | 7.073 | 7 / 10 / 13 |
| **`context_memory_B25`** | **CARR (ours)** | **4,539.62** | **5.458** | **5 / 8 / 10** |

![Sample-mean Pareto frontier](assets/pareto_frontier.png)

The sample-mean frontier contains Bootstrap, Exact-G4, CARR-NoRecall, CARR,
and Exact-B25. CARR is not point-dominated, but this does not override the
failed non-inferiority test.

![Root-level paired comparisons](assets/superiority_forest.png)

</details>

<details>
<summary>Exploratory appendix evidence and provenance</summary>

The directory [`carr_rl_lite_exp/`](carr_rl_lite_exp/) contains the additional
development-only and post-hoc checks reported in the appendix: the
development-tuned learned gate, the matched G5 generation-cap comparison,
one-at-a-time threshold sensitivity, logical-call timing diagnostics, and
bootstrap frontier stability. These checks are explicitly separated from the
frozen Experiment B confirmatory matrix. The directory also contains a small,
post-confirmatory [controlled wall-clock microbenchmark](carr_rl_lite_exp/CONTROLLED_RESOURCE_MEASUREMENT.md)
showing why logical generator calls are not a wall-clock or energy proxy on
this small-CNN backbone. These checks neither change the primary estimand nor
enter the six-comparison multiplicity family.

For the learned holdout check, the archived historical report's `6.51 vs
6.50` values are effective post-bootstrap guidance publications, not generator
invocations. The accompanying raw-counter projection records the unambiguous
total generator-call means (`4.83` learned vs `5.38` rule CARR) while retaining
the historical report unchanged for provenance.

Two bootstrap streams are kept separate on purpose:

- `reports/posthoc_review_sensitivity_2026-08-03.json` is the canonical
  `seed=20260803` source for the log-ratio and call-difference sensitivity
  analyses;
- `carr_rl_lite_exp/results/carr_rl_lite/expB_pareto_bootstrap.json` is the
  `seed=20260715` source for the reported 100% CARR non-dominance and 99.97%
  point-dominance frequency against Exact-G5.

The 99.96% value obtained when the frontier check reuses the first stream is a
one-resample Monte-Carlo difference, not a substantive discrepancy. The
paper's reported number is backed by the dedicated Pareto report above.

</details>

<details>
<summary>Scope of the compact result files</summary>

`compact_runs.csv` contains outcomes, logical call counts,
generation/reactivation counts, safety flags, and within-cell pairing hashes.
Here `reactivation` is the frozen implementation and audit-field name for the
paper's recall action.
The compact records omit hostnames, filesystem paths, process identifiers,
timestamps, and environment fingerprints.

`compact_b_analysis.json` contains the complete computed numerical result.
The compact layer supports result reproduction and matrix-level checks; it
does not replace trace-level inspection of the original simulator logs.

</details>

## Citation

If you use CARR or its reproducibility artifact, please cite the paper:

```bibtex
@inproceedings{ma2026carr,
  title={Budgeted Guidance Refresh Control: A Paired Throughput--Call Study in Lifelong Multi-Agent Path Finding},
  author={Ma, Xiaoxiao and Fang, Quan and Jiang, Xiankun},
  booktitle={The Eighth International Conference on Distributed Artificial Intelligence},
  year={2026}
}
```

Machine-readable software and paper citation metadata are provided in
[`CITATION.cff`](CITATION.cff).

## License

This project is released under the [MIT License](LICENSE).
Copyright (c) 2026 Xiaoxiao Ma.

The upstream OnlineGGO copyright and license notice are retained in
[`patches/OnlineGGO-LICENSE`](patches/OnlineGGO-LICENSE); see
[`patches/README.md`](patches/README.md) for the pinned revision and patch
provenance.
