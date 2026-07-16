# DAI 2026 Research Track review package

This directory is the self-contained, anonymous ACM `sigconf` review version
of the Experiment B manuscript. It preserves the research content and frozen
Experiment B results from `../main.tex`, while using a cleaner DAI/ACM review
shell.

## Official constraints applied

- English PDF submitted through OpenReview.
- Up to 8 main-text pages; references are excluded from the limit.
- An unlimited appendix may follow the bibliography, but reviewers are not
  required to read it.
- Double-blind review: no author names, affiliations, acknowledgments, or
  identifying supplementary material.
- ACM LaTeX; DAI explicitly accepts two-column `sigconf` submissions.
- Review class: `\documentclass[sigconf,review,anonymous]{acmart}`.
- No sample Woodstock/2018 DOI/ISBN/copyright metadata.
- Real camera-ready rights metadata must come from ACM eRights/TAPS after
  acceptance.

Official source:
https://www.adai.ai/dai/2026/research-track.html

## Package contents

- `main.tex`: anonymous review manuscript.
- `references.bib`: bibliography used by the manuscript.
- `figures/carr_framework.tex`: paper-native vector overview of the CARR
  control plane and frozen LMAPF data plane.
- `figures/b_pareto_frontier.pdf`: Experiment B Pareto figure.
- `figures/b_superiority_forest.pdf`: Experiment B forest plot.
- `main.pdf`: locally compiled review PDF.

All three figures are self-contained in the package and have ACM
`\Description` text for accessibility.

## Compile

Compile from this directory, or set `main.tex` as the main document in
Overleaf:

```sh
latexmk -pdf main.tex
```

If `latexmk` is unavailable:

```sh
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

## Mandatory final checks

1. Confirm that the bibliography begins after no more than 8 pages of main
   text.
2. Confirm that line numbers, figures, tables, references, and appendix render
   without clipping or overflow.
3. Search the PDF and source package for author names, affiliations, emails,
   acknowledgments, non-anonymous URLs, file metadata, and identifying paths.
4. Keep the OpenReview AI-use disclosure synchronized with the actual use of
   generative-AI tools.
5. Do not add DOI, ISBN, copyright-year, or rights text until ACM provides the
   accepted-paper metadata.
6. For camera-ready production, export the final CCSXML block from the ACM CCS
   generator and restore authors, affiliations, emails, and acknowledgments.

The package was compiled locally with Tectonic and visually checked page by
page. The current review PDF has 9 total pages: the main paper occupies pages
1--8, the bibliography begins after the conclusion on page 8, and the appendix
continues on page 9. Because Tectonic's cached `acmart` version can differ from
Overleaf's current official template, repeat the page-count check once on the
final submission platform.
