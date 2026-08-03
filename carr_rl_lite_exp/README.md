# CARR-RL-lite — Development-tuned controller comparison (supplementary artifact)

This directory archives the **development-only, exploratory** artifacts behind
three appendix analyses of the paper *"Budgeted Guidance Refresh Control: A
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
> `9eb203c1caf31f81409787a699a88ebc025071977192ec95b25390b5cc2b5538`) was never
> modified.

## Layout

```
scripts/
  run_carr_rl_lite_dev.py        # dev-only runner adding the `context_learned_lite` arm
  make_dev_runner.py             # generator for the above (patches the frozen v1 runner; never edits it)
  carr_rl_lite_extract.py        # offline feature/decision-row extractor
  carr_rl_lite_train.py          # lightweight policy training (raw4 vs fullstate)
  run_carr_rl_lite_ab_train.sh   # (alpha,beta) selection grid (dev seeds 17-20)
  run_carr_rl_lite_ab_holdout.sh # held-out evaluation (dev seeds 21-26)
results/
  carr_rl_lite/
    ab/                          # candidate (alpha,beta) policy files
    ab_train/                    # selection-grid matrices + selection.json
    ab_holdout/                  # held-out matrices + report.json (key verdict)
    model/                       # raw4/fullstate policy + agreement/AUC report
    advantage/                   # sign-advantage diagnostic report
    matrix_a/                    # earlier (flawed) GBDT-gate matrix, kept for provenance
    expB_posthoc_robustness.json  # Appendix B log-ratio sensitivity + frontier-stability (seed 20260803)
    expB_genlatency.json         # Appendix B generator-latency aggregate
    expB_pareto_bootstrap.json   # Appendix B frontier-stability frequencies
    expF_g5cap.json              # Appendix D (G5Cap) summary
    expG_threshsens.json         # Appendix A threshold-sensitivity summary
  path_f_g5cap_dev/              # G5Cap dev matrices (CSV)
  path_g_threshold_sweep/        # threshold-sweep dev matrices (CSV)
```

## Key numbers (as reported in the paper)

* **Learned gate vs frozen rule (held-out seeds 21–26, 72 cells):** mean
  throughput effect **−1.07%** (95% CI [−2.01, −0.13]); mean calls **6.51 vs
  6.50**; 4/6 roots negative; exploratory one-sided exact root sign-flip
  **p ≈ 0.91**. Selection used only seeds 17–20. See
  `results/carr_rl_lite/ab_holdout/report.json`.
* **Mechanism:** the four intuitive raw signals reproduce rule acceptance at
  only **AUC ≈ 0.52**, whereas the controller's causal state reproduces it at
  **98.2%** agreement. See `results/carr_rl_lite/model/report.json`.
* **CARR-G5Cap vs Exact-G5 (matched five-generation ceiling):** **+0.83%**
  (7/10 roots positive), realized 5.00 vs 6.00 mean calls. See
  `results/carr_rl_lite/expF_g5cap.json`.
* **Generator latency (diagnostic only):** 30,015 calls, 0.0125 s/call pooled;
  0.0713 s per CARR run vs 0.3117 s per Exact-B25 run. These runs were marked
  `timing_evidence_valid=false`; not controlled wall-clock/energy evidence. See
  `results/carr_rl_lite/expB_genlatency.json`.
* **Frontier stability (10,000 whole-root bootstrap resamples):** CARR
  non-dominated in 100% and point-dominated Exact-G5 in 99.96–99.97% (the two
  values differ only by bootstrap seed / Monte-Carlo noise). See
  `results/carr_rl_lite/expB_pareto_bootstrap.json`.
* **Threshold sensitivity (narrow_r020, dev):** all one-at-a-time effects
  stayed negative; max absolute departure from the frozen effect **0.637 pp**.
  See `results/carr_rl_lite/expG_threshsens.json`.
* **Post-hoc robustness (Appendix B):** log-ratio sensitivity and frontier-stability
  frequencies recomputed from `compact_runs.csv` (seed 20260803) are archived in
  `results/carr_rl_lite/expB_posthoc_robustness.json`.
