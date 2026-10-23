# Contributing to CARR

Thank you for your interest in the **Context-Aware Refresh and Recall (CARR)** reproducibility artifact for the DAI 2026 Oral paper.

## Purpose

This repository packages the frozen confirmatory evidence and portable analysis for an academic paper. The primary goals are reproducibility, transparency, and auditability of the reported numerical results.

## Running Tests

Run the test suite from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

For a quick check of the compact result artifact:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest -v tests.test_compact_b_artifact
```

The test suite:
- Regenerates the development runner from the frozen v1 runner
- Validates compact exploratory summaries against their public CSVs
- Reproduces the post-hoc report byte-for-byte
- Checks that committed results contain no machine-specific paths or hostnames

## Running Compact Analysis

The lightweight, portable analysis requires only Python's standard library:

```bash
python3 scripts/analyze_compact_b.py --output reproduced/compact_b_analysis.json --force
```

This validates the complete matrix, pairing fingerprints, safety flags, and conservation laws before recomputing method summaries, paired root-level effects, bootstrap intervals, exact sign-flip tests, Holm correction, all three non-inferiority gates, and the sample-mean Pareto frontier.

## Paper ↔ Repository Mapping

To help readers navigate between the paper and the code:

### Terminology

| Paper term | Implementation name | Notes |
|---|---|---|
| **hold** | `hold` | Keep the current active guidance |
| **recall** | `reactivate` | Retrieve compatible historical guidance from the cache |
| **generate** | `generate` | Invoke the frozen CNN to produce fresh guidance |

The frozen confirmatory implementation uses `reactivate` in operation names, configuration identifiers, and audit fields for the action called **recall** in the paper.

### Evidence Paths

- **Compact confirmatory evidence**: `results/same_call_confirmation_b/compact_runs.csv` and `reports/compact_b_analysis.json` contain the complete numerical results reported in the paper.
- **Full experiment**: The entry point is `scripts/run_same_call_confirmation_b.py`. A complete rerun requires the trained CNN checkpoint and a native OnlineGGO build, which are not bundled for portability.
- **Appendix evidence**: The directory `carr_rl_lite_exp/` contains development-only and post-hoc checks (learned gate, matched G5 comparison, threshold sensitivity, logical-call timing diagnostics, bootstrap frontier stability, and the controlled wall-clock microbenchmark). These are explicitly separated from the frozen confirmatory matrix.

See the README for detailed reproduction steps, hash verification, and scope notes.

## Pull Request Guidelines

We welcome contributions that improve clarity, portability, and reproducibility. When opening a pull request:

1. **Describe the motivation**: Explain what problem the PR solves or what improvement it provides.
2. **Keep changes focused**: One logical improvement per PR makes review easier.
3. **Preserve numerical results**: Do not change the frozen confirmatory evidence files (`results/same_call_confirmation_b/`, `reports/compact_b_analysis.json`, `reports/posthoc_review_sensitivity_2026-08-03.json`) unless you are correcting a confirmed error. If you believe a correction is needed, open an issue first to discuss.
4. **Preserve appendix provenance**: The `carr_rl_lite_exp/` directory contains historical development artifacts and post-hoc checks. Changes that improve clarity or fix bugs are welcome; changes that alter reported numbers should be discussed first.
5. **Run tests**: Ensure `python3 -m unittest discover -s tests -v` passes before opening the PR.
6. **Check portability**: If your change affects the analysis or runner scripts, verify that the compact analysis still runs with only the standard library.

### What Belongs in a PR

✅ **Good candidates for PRs:**
- Documentation improvements (clarifying setup, mapping paper terms to code, adding examples)
- Portability fixes (making tests or scripts work on more platforms)
- Test coverage improvements
- Bug fixes that do not change numerical results
- Dependency updates (with caution; prefer minimal dependencies)

⚠️ **Discuss first:**
- Changes to frozen confirmatory evidence or analysis outputs
- Removal or major restructuring of the `carr_rl_lite_exp/` appendix artifacts
- Changes to repository layout, branch protection, or CI policy
- Alterations to academic claims, scope statements, or numerical interpretations

### Irreversible Changes

For changes that affect repository policy, license, author attribution, or numerical provenance, please open an issue to discuss the approach before submitting a PR. This ensures alignment with the paper's commitments and the artifact's long-term stability.

## Large Appendix Evidence

The directory `carr_rl_lite_exp/` contains secondary development and post-hoc evidence. While it is tracked in the repository, it is not part of the primary confirmatory chain. Pull requests may improve its clarity or fix bugs, but wholesale removal or restructuring should be discussed via issue first.

## Code of Conduct

We are committed to fostering a welcoming, respectful environment. This is an academic reproducibility artifact, and discussions should focus on the technical content. Please:

- Be respectful and constructive
- Assume good intent
- Focus on the technical merit of ideas
- Acknowledge that this is a frozen research artifact with specific inferential scope

Harassment, personal attacks, and off-topic discussions are not acceptable.

## Questions?

If you have questions about the paper, the reproducibility artifact, or the best way to contribute, please open an issue. We're here to help!

---

**Artifact maintainers:** Xiaoxiao Ma, Quan Fang, Xiankun Jiang  
**Institution:** Beijing University of Posts and Telecommunications  
**Paper:** DAI 2026 (Oral Presentation)
