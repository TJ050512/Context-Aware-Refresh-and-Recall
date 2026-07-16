# Locked-test protocol amendment v3

Status: **frozen before any locked-test seed is opened**, 2026-07-14.

This amendment completes the previously skeletal locked-test specification. It
does not authorize a run by itself. The launcher remains blocked until the
complete validation-v2 analysis passes its integrity gate, at least one of the
predeclared causal-quality or context-validation candidate paths passes, and
the user explicitly confirms the one-shot test after seeing that decision.

## Workload scope amendment

The early trigger protocol described four workloads: stationary, abrupt,
recurrent, and gradual. The subsequently frozen validation-v2 treatment and
the implemented claim-aware absolute-tape runner define exactly three:
`stationary`, `abrupt`, and `recurrent`. Locked test v3 therefore uses those
same three treatments.

This is a reduction of scope, not evidence about the omitted condition. No
locked-test conclusion, robustness statement, or SOTA language from this
study covers gradual drift. A future gradual-drift claim requires a separately
specified treatment, development-free implementation audit, and new held-out
evaluation; it cannot be inferred from v3.

## Locked matrix

The one-shot split remains the authoritative 30-seed block 1001--1030. Every
artifact must include all 30 seeds, all 13 registered methods, and all three
workloads. The registered family is:

`uniform`, `bootstrap_only`, `always`, `exact_even_B25`, `period_80`,
`random_B25`, `js_B25`, `js_cap_B25`, `context_memory_B25`,
`throughput_drop_B25`, `causal_block_B25`, `proposed_cohort_B25`, and
`proposed_no_cohort_B25`.

`random_memory_B25` remains development-only and is prohibited.

The four scenarios are:

| Artifact | Map | Free cells | Density | Agents |
|---|---|---:|---:|---:|
| `warehouse_r020` | `warehouse_60x100_kiva` | 3,686 | 0.20 | 737 |
| `warehouse_r035` | `warehouse_60x100_kiva` | 3,686 | 0.35 | 1,290 |
| `sortation_r020` | `sortation_small_kiva` | 1,564 | 0.20 | 313 |
| `sortation_r035` | `sortation_small_kiva` | 1,564 | 0.35 | 547 |

Agent counts are `round(density * free_cells)`. Thus the confirmatory matrix is
2 maps x 2 densities x 3 workloads x 30 root seeds x 13 methods = **4,680
runs**, or 1,170 runs in each of four protected artifacts. The statistical
unit is the root seed clustered across all 12 map-density-workload cells.

The common treatment is H=2000, D=20, warm-up=200, release interval=110,
guard suffix=4, and sigma=.75. `context_memory_B25` remains frozen at recall
threshold .05, recall margin .02, minimum score .10, minimum gap 6,
maintenance age 25, and maintenance stability .20. Four artifacts run
concurrently with `jobs=3`; their timing fields are diagnostic and cannot
support a generator-time claim.

## Minimal warehouse-map repair

The held-out `warehouse_60x100_kiva.map` payload was intact, but its first two
header lines were malformed. Before any locked seed was opened, only these two
lines were repaired:

- `typW octilW` -> `type octile`
- `hWight 60` -> `height 60`

No grid row changed. The pre-repair SHA-256 was
`19a8ed65ce0d9c79650adf47299011e9b0843c93c27f68d46f3228a5aec0a049`;
the repaired 60x100 map SHA-256 is
`29bde647469ea50e0ec6f605396f0893a24b0a43696014734b095bda89ce60f1`.
It contains 3,686 passable cells. The untouched `sortation_small_kiva.map`
SHA-256 is
`7a2ec55f0afc2e5969f15cdb19fefea47d2dbab2aafb51632d54e5e7f9c4e2e1`.

## Mechanical safeguards

The v3 launcher requires all of the following rather than relying on a comment
or convention:

1. explicit `WORKSPACE`, `DAI_PYTHON`, `CKPT10`, and `VALIDATION_GATE_JSON`
   environment variables;
2. a validation-v2 analysis JSON with fresh evidence, a passing integrity
   audit, the complete 1,560-run validation design, and at least one passing
   predeclared candidate path;
3. the exact environment acknowledgement
   `DAI_LOCKED_TEST_CONFIRM=I_CONFIRM_ONE_SHOT_LOCKED_TEST_V3`;
4. the command-line flag `--confirm-locked-test-v3`, which is distinct from
   and additional to the runner's `--confirm-locked-test` flag;
5. frozen runner, checkpoint, simulator, protocol, map, and audit hashes;
6. no pre-existing JSON or CSV at any of the four protected output paths.

Once any member is opened, all four artifacts must be completed. Selective
reruns, arm deletion, output replacement, and post-outcome treatment changes
are prohibited. The machine-readable source of truth is
`configs/locked_test_protocol_v3.json`.
