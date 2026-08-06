# CARR-RL-lite — Development-tuned controller comparison (supplementary artifact)

This directory archives the **development-only, exploratory** artifacts behind
the appendix analyses of the paper *"Budgeted Guidance Refresh Control: A
Paired Throughput–Call Study in Lifelong Multi-Agent Path Finding"* (DAI 2026):

* **Appendix C — Development-tuned controller comparison** (the
  "CARR-RL-lite" learned hold/generate gate),
* **Appendix D — Development-only hard-cap comparison** (`CARR-G5Cap`),
* **Appendix B — generator-latency diagnostics** and **whole-root bootstrap
  Pareto-frontier stability**,
* **Appendix A — one-at-a-time threshold sensitivity**.

> **Scope.** Everything here is development-only and descriptive. It uses only
> development seeds (17–26); all confirmatory roots of Experiment B remain
> untouched, and none of these checks alter the prespecified confirmatory
> analysis, estimands, or multiplicity correction. The frozen v1 runner
> (`scripts/run_same_call_confirmation_v1.py`, SHA-256
> `998e321877e660b5d13618b74905040df258f95657490e764e92cc4b117194eb`) was never
> modified.

> **See also `CONTROLLED_RESOURCE_MEASUREMENT.md`** for a post-confirmatory
> controlled (`timing_evidence_valid=true`) wall-clock microbenchmark that
> quantifies exactly what the paper's "logical generator call" does and does
> not correspond to on the evaluation host.

## Layout

```
scripts/
  run_carr_rl_lite_dev.py        # dev-only runner adding the `context_learned_lite` arm
  make_dev_runner.py             # generator for the above (patches the frozen v1 runner; never edits it)
  carr_rl_lite_extract.py        # offline feature/decision-row extractor
  carr_rl_lite_train.py          # lightweight policy training (raw4 vs fullstate)
  run_carr_rl_lite_ab_train.sh   # (alpha,beta) selection grid (dev seeds 17-20)
  run_carr_rl_lite_ab_holdout.sh # held-out evaluation (dev seeds 21-26)
  verify_public_summaries.py     # stdlib verification of all public summaries
results/
  carr_rl_lite/
    ab/                          # candidate (alpha,beta) policy files
    ab_train/                    # selection-grid matrices + selection.json
    ab_holdout/                  # held-out matrices + report.json (key verdict)
    model/                       # raw4/fullstate policy + agreement/AUC report
    advantage/                   # sign-advantage diagnostic report
    matrix_a/                    # earlier (flawed) GBDT-gate matrix, kept for provenance
    expB_genlatency.json         # Appendix B generator-latency aggregate
    expB_pareto_bootstrap.json   # Appendix B frontier-stability frequencies
    expF_g5cap.json              # Appendix D (G5Cap) summary
    expG_threshsens.json         # Appendix A threshold-sensitivity summary
  path_f_g5cap_dev/              # G5Cap dev matrices (CSV)
  path_g_threshold_sweep/        # threshold-sweep dev matrices (CSV)
ARTIFACT_SHA256.json             # checksums for compact reports and scripts
CONTROLLED_RESOURCE_MEASUREMENT.md # controlled timing scope and interpretation
```

## Key numbers (as reported in the paper)

* **Learned gate vs frozen rule (held-out seeds 21–26, 72 cells):** mean
  throughput effect **−1.07%** (95% CI [−2.01, −0.13]); mean effective
  post-bootstrap publications **6.51 vs 6.50** and mean total generator calls
  **4.83 vs 5.38**; 4/6 roots negative; exploratory one-sided exact root
  sign-flip **p ≈ 0.91**. Selection used only seeds 17–20. See the historical
  `results/carr_rl_lite/ab_holdout/report.json` and the counter-corrected
  `results/carr_rl_lite/ab_holdout/resource_counts_summary.json`.
* **Mechanism:** the four intuitive raw signals reproduce rule acceptance at
  only **AUC ≈ 0.52**, whereas the controller's causal state reproduces it at
  **98.2%** agreement. See `results/carr_rl_lite/model/report.json`.
  The report's legacy free-text interpretation calls the full-state AUC
  "high"; the claim here deliberately uses the numeric agreement value
  (0.9822), because the archived numeric AUC is 0.4304.
* **CARR-G5Cap vs Exact-G5 (matched five-generation ceiling):** **+0.83%**
  (7/10 roots positive), realized 5.00 vs 6.00 mean calls. See
  `results/carr_rl_lite/expF_g5cap.json`.
* **Generator latency (diagnostic only):** 30,015 calls, 0.0125 s/call pooled;
  0.0713 s per CARR run vs 0.3117 s per Exact-B25 run. These runs were marked
  `timing_evidence_valid=false`; not controlled wall-clock/energy evidence. See
  `results/carr_rl_lite/expB_genlatency.json`.
* **Controlled timing boundary (development-only; two runs per method):** CARR
  used 43.3% less generator-only time than Exact-B25 but had 10.2% higher mean
  end-to-end time. The unweighted mean run-level CNN latency was 1.83 ms/call
  (pooled ratio 1.66 ms/call). This is descriptive evidence that logical calls
  are not a physical-resource proxy, not an acceleration claim. See
  `CONTROLLED_RESOURCE_MEASUREMENT.md`.
* **Frontier stability (10,000 whole-root bootstrap resamples):** CARR
  non-dominated in 100% and point-dominated Exact-G5 in **99.97%** using the
  dedicated `seed=20260715` Pareto stream. Reusing the separate post-hoc stream
  yields 99.96%; the one-resample difference is Monte-Carlo noise. See
  `results/carr_rl_lite/expB_pareto_bootstrap.json`.
* **Threshold sensitivity (narrow_r020, dev):** all one-at-a-time effects
  stayed negative; max absolute departure from the frozen effect **0.637 pp**.
  See `results/carr_rl_lite/expG_threshsens.json`.
* **Post-hoc robustness (Appendix B):** log-ratio and call-difference
  sensitivity results recomputed from `compact_runs.csv` with `seed=20260803`
  are archived canonically in
  [`../reports/posthoc_review_sensitivity_2026-08-03.json`](../reports/posthoc_review_sensitivity_2026-08-03.json).

## Verify the packaged evidence

From the repository root, the following standard-library command recomputes
the statistics recoverable from the public development CSVs, validates the
compact diagnostic reports (including the controlled microbenchmark) and
their SHA-256 manifest, and rejects committed result files containing
machine-specific absolute paths or host values:

```bash
python3 carr_rl_lite_exp/scripts/verify_public_summaries.py
```

The post-hoc Experiment B robustness report has a separate byte-for-byte
reproduction path:

```bash
python3 scripts/analyze_posthoc_review_sensitivity.py \
  --csv results/same_call_confirmation_b/compact_runs.csv \
  --output reproduced/posthoc_review_sensitivity_2026-08-03.json \
  --seed 20260803 --bootstrap-samples 10000
cmp reproduced/posthoc_review_sensitivity_2026-08-03.json \
  reports/posthoc_review_sensitivity_2026-08-03.json
```

To verify that the development runner is derived from the committed frozen v1
runner without editing it:

```bash
python3 carr_rl_lite_exp/scripts/make_dev_runner.py
git diff --exit-code -- carr_rl_lite_exp/scripts/run_carr_rl_lite_dev.py
```

## Full development reruns

The shell launchers are path-portable and accept `PYTHON`, `WORKSPACE`,
`CKPT`, and `MAPDIR` overrides. A full rerun still requires the external
OnlineGGO reconstruction and the frozen CNN checkpoint described in the root
README. For example:

```bash
PYTHON=/path/to/python \
CKPT=/path/to/optimal_update_model_20000.json \
MAPDIR=/path/to/benchmark-lifelong/maps \
bash carr_rl_lite_exp/scripts/run_carr_rl_lite_ab_holdout.sh
```

The large raw simulator JSONs and logs are intentionally excluded; the
reviewer-facing CSV matrices, compact reports, policy files, and decision-row
tables needed for the documented offline checks are included.
