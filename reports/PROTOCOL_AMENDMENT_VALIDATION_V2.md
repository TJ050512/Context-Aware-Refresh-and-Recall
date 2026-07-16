# Protocol amendment: fresh validation-v2 split

Status: **frozen before the first validation-v2 run** on 2026-07-14.

This amendment replaces the ambiguous validation label without changing any
policy logic or parameter.  The development artifact
`results/official_gate0/claim_full_dev10_h2000_v7.json` was frozen at SHA-256
`d971c23983bb9e2b1bc517cea0db19fd5da5bc97a16b6a2aa3a777c06b7ff9f7`.
That SHA is the recorded derivation commitment for the following authoritative
fresh seed vector:

`[320019, 241771, 827130, 693142, 741084, 12102, 133633, 876480, 50620, 131545]`

No member of this vector had been executed when the amendment was frozen.  A
validation-v2 artifact must contain the complete vector, all three workloads
(`stationary`, `abrupt`, and `recurrent`), and the complete 13-method formal
registry.  The runner refuses subsets and refuses to overwrite an existing
validation-v2 artifact.

The complete matrix is four artifacts: `warehouse_small_narrow_kiva` at 218
and 382 agents (density robustness on the already-developed topology), plus
the previously unused `warehouse_small_kiva` at 255 and 447 agents (fresh
topology), always with H=2000, D=20, warm-up=200, release interval=110, and
sigma=.75.  This is 2 maps x 2 densities x 3 workloads x 10 root seeds x 13
methods = 1,560 runs.  Once any fresh seed is opened, all four artifacts must
be completed; the independent statistical unit is the root seed clustered
across its 12 map-density-workload cells.

The frozen `context_memory_B25` parameters are recall threshold .05, recall
margin .02, minimum score .10, minimum gap 6, maintenance age 25, and
maintenance stability gate .20.  The exact integrity, quality, efficiency,
near-exact-language, and scoped best-controller gates are machine-readable in
`configs/claim_validation_protocol_v2.json`; they must not be changed after a
validation-v2 run begins.

The four validation artifacts run in parallel and therefore do not constitute
timing evidence.  They may provisionally freeze an efficiency candidate using
the call-count gate, but the >=80% generator-time reduction condition remains
pending until a separate jobs=1 exclusive-timing run is complete.  Concurrent
`generator_seconds` values are diagnostic only.

## Legacy-label handling

Seeds 101--110 are no longer called `validation`.  Their canonical label is
`contaminated_pilot_validation`; they are pilot evidence only and cannot support
a fresh-validation claim.  For cautious command-line compatibility, the runner
accepts the old spelling `validation` but immediately canonicalizes it, so any
new artifact is written with the contaminated label.  Existing artifacts whose
split is `validation` and whose seeds are 101--110 must be interpreted the same
way.

## Frozen formal method family

The formal family contains 13 methods:

`uniform`, `bootstrap_only`, `always`, `exact_even_B25`, `period_80`,
`random_B25`, `js_B25`, `js_cap_B25`, `context_memory_B25`,
`throughput_drop_B25`, `causal_block_B25`, `proposed_cohort_B25`, and
`proposed_no_cohort_B25`.

`random_memory_B25` remains available for development-result reproduction but
is not formally registered.  Its H=2000 development screen was effectively
tied with `random_B25` (4186.633 versus 4186.600 mean completed tasks), produced
only three recalls across 30 runs, and saved approximately 0.4% of generator
calls.  It therefore cannot be selected in validation-v2 or locked test.

## Locked resources

The locked-test seeds remain exactly 1001--1030; this amendment does not touch
them.  Sortation maps also remain sealed for locked test and are rejected by the
runner on development, contaminated-pilot, and validation-v2 splits.

The machine-readable source of truth is
`configs/claim_validation_protocol_v2.json`.
