# DAI 2026 research workspace

This directory separates the original coursework artifact from the research code that will be used for paper claims.

The current paper studies when global guidance should be refreshed in lifelong
multi-agent path finding. Its main empirical evidence is the frozen Experiment
B: 3,840 runs across 40 independent root clusters. The registered 1%
non-inferiority objective was not supported; the supported result is a paired
throughput--generator-call Pareto trade-off. See
`reports/SAME_CALL_B_DECISION_2026-07-15.md` for the exact claim boundary.

- `coursework_baseline/`: an unchanged copy of the submitted reproducibility package. It is evidence of the starting point, not the paper implementation.
- `RESEARCH_DESIGN.md`: current novelty assessment, research questions, baseline ladder, experiment protocol, and submission gates.
- `KNOWN_VALIDITY_ISSUES.md`: issues that invalidate the current numerical claims until fixed.
- `OFFICIAL_BACKBONE_AUDIT.md`: pinned OnlineGGO source audit, refresh/reuse semantics, direction-order risk, and platform preflight.
- `OFFICIAL_GATE0_RUNBOOK.md`: exact Linux build, semantic sentinels, and first official experiment sequence.
- `SELECTIVE_REPAIR_EXPERIMENT.md`: historical selective stale-field repair protocol and locked No-Go result.
- `GUIDANCE_VERSIONING_EXPERIMENT.md`: current source-aligned paper hypothesis and official experiment gate.
- `RESEARCH_STATUS.md`: compact decision log with completed runs, negative results, and the current blocker.
- `PAPER_WRITING_GUIDE.md`: safe-to-write sections, forbidden claims, and planned result tables while official runs are pending.
- `configs/pilot_protocol.yaml`: machine-readable specification for the first correctness and non-stationary pilot runs.
- `configs/guidance_versioning_gate0.json`: frozen official OnlineGGO feasibility manifest for the first Linux run.
- `src/dai_lmapf/`: planner-independent scenario, task, controller, and safety interfaces for the new research implementation.
- `tests/`: correctness tests that run without third-party dependencies.

The first implementation milestone is a correctness gate. No new throughput result should be reported until every simulated step is checked for vertex and edge-swap collisions and task generation excludes zero-distance shortcuts.

The locked smoke validation has completed, but it modeled eager global guidance
recomputation. Official source inspection showed that OnlineGGO's GPIBT update
is future-only. A subsequent locked selective-repair diagnostic was also
No-Go. Treat both smoke results as diagnostic; the current claim-bearing plan
is route-cohort-aware guidance publication.

Run the current foundation tests with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Repository contents

- `src/dai_lmapf/`: planner-independent controllers, protocols, invariants,
  task generation, and OnlineGGO adapters.
- `scripts/`: experiment drivers, frozen analyzers, integrity audits, and
  paper-figure generation.
- `configs/`: machine-readable frozen protocols and experiment manifests.
- `tests/`: correctness, safety, publication-policy, and analysis tests.
- `paper/`: canonical anonymous manuscript source (`main.tex`).
- `reports/`: decision memos, integrity evidence, and compact frozen analyses.
- `results/`: compact CSV tables and selected analysis summaries only.
- `patches/`: the pinned OnlineGGO source patch and experiment configs.

## Reconstruct the OnlineGGO backbone

The modified third-party checkout is intentionally not embedded as a nested
Git repository. Reconstruct it from the pinned upstream revision and recorded
patch with:

```bash
bash scripts/setup_onlineggo.sh
```

See `patches/README.md` for provenance and licensing details.

## Main paper evidence

The Experiment B evidence should be read in this order:

1. `reports/same_call_confirmation_b_analysis.json`
2. `reports/same_call_confirmation_b_analysis.md`
3. `reports/SAME_CALL_B_DECISION_2026-07-15.md`
4. `results/same_call_confirmation_b/*.csv`

The four large raw Experiment B JSON files, attempt ledgers, logs, temporary
files, and local credentials are excluded from ordinary Git history. Their
integrity hashes remain in the reports. The complete raw archive should be
published separately as a versioned release asset or archival dataset, then
linked here; it should not be force-added to this repository.

## Paper build and figures

Build instructions and evidence precedence are in `paper/README.md`. The data
figures require `reportlab`; the foundation test suite uses only the project
source tree and Python's standard test runner.

Optional dependencies are grouped by task:

```bash
python3 -m pip install -e '.[causal]'           # NumPy controller utilities
python3 -m pip install -e '.[cnn]'              # frozen CNN inference
python3 -m pip install -e '.[figures]'          # paper figures
python3 -m pip install -e '.[checkpoint-tools]' # checkpoint extraction
```

## License status

No license has yet been selected for the original code in this repository.
Until one is added, the default copyright rules apply. The OnlineGGO patch is
derived from the MIT-licensed upstream project; its license notice is retained
under `patches/OnlineGGO-LICENSE`.
