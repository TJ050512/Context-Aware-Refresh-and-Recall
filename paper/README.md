# DAI 2026 paper source

Canonical manuscript source: `main.tex`.

The manuscript follows the ACM `sigconf` review format required by the DAI
2026 Research Track. It is anonymous and targets eight main-body pages,
excluding references; the appendix follows the bibliography.

## Evidence precedence

The manuscript's main empirical evidence is Experiment B (3,840 runs, 40 fresh
root clusters). Use these sources, in order:

1. `../reports/same_call_confirmation_b_analysis.json`
2. `../reports/same_call_confirmation_b_analysis.md`
3. `../reports/SAME_CALL_B_DECISION_2026-07-15.md`

The earlier A2 study (960 runs, 10 roots) is prior evidence with a disjoint root
sample. It informed B's sample-size planning and is disclosed, but is **never
pooled** with B; do not merge their numbers. Do not copy claims, numbers,
experiment lists, or timing language from
`../PAPER_METHOD_EXPERIMENTS_DRAFT.md` or any pre-A2 registration draft.

All current-study design numbers and primary/secondary effect estimates in
`main.tex` are drawn from Experiment B. A2 numbers appear only in the explicit
prior-evidence disclosure required by the B protocol. When in doubt, re-read
the B analysis JSON rather than substituting an A2 estimate.

The pre-specified B primary objective is the standalone 1% non-inferiority test
against `exact_even_B25`; it failed. Sparse-comparator and Pareto results are
pre-specified secondary analyses and must not be presented as replacing the
failed primary objective.

## Local build

With a TeX distribution containing `acmart` and `latexmk`:

```bash
latexmk -pdf main.tex
```

The current machine does not have a TeX distribution, so this initial source
has not yet received compile-time or page-count QA. Before submission, compile
with the current ACM template, inspect every page, and keep essential evidence
within the eight-page main body.

## Generated figures

- `../output/pdf/b_framework.pdf` (Fig. 1, CARR system overview)
- `../output/pdf/b_pareto_frontier.pdf` (Fig. 2, operating points)
- `../output/pdf/b_superiority_forest.pdf` (Fig. 3, superiority contrasts)

Regenerate the two data figures from the frozen Experiment B JSON, and the
schematic framework figure from its own script, with:

```bash
python3 ../scripts/make_b_paper_figures.py   # Pareto + forest, data-driven
python3 ../scripts/make_framework_figure.py  # framework schematic (no data)
```

All three require `reportlab` (e.g. `pip install reportlab` in a virtualenv).
`make_framework_figure.py` is a pure layout script and reads no experiment data,
so it never encodes a numeric claim. The A2 figures (`a2_*.pdf`,
`make_a2_paper_figures.py`) are retained only for the superseded 960-run draft
and are no longer referenced by `main.tex`.

## Name mapping

- `CARR` = `context_memory_B25`
- `CARR-NoRecall` = `context_no_reactivation_B25`

These are presentation names only; no evaluated behavior was changed.
