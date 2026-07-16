# Validation map/density preflight

Audit date: 2026-07-14 (Asia/Shanghai)

This is a read-only preflight. It does not open a fresh validation seed or a
locked-test seed, and it does not change the registered runner policy.

## Map identity and capacity

The local and AutoDL copies are byte-identical. Both files are under
`external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps/` in their
respective workspaces.

| Map | Dimensions | Free cells | W homes | E endpoints | SHA-256 |
|---|---:|---:|---:|---:|---|
| `warehouse_small_narrow_kiva.map` | 33 x 57 | 1,091 | 44 | 532 | `866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6` |
| `warehouse_small_kiva.map` | 33 x 57 | 1,277 | 40 | 342 | `0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd` |

The count uses the runner's exact parser rule in
`dai_lmapf.absolute_workload.read_kiva_map`: a location is free when its map
character is neither `@` nor `T`. Neither audited map contains `T`.

The requested integer counts implement **nearest-integer rounding**, not
flooring at both densities:

| Map | rho | Raw count | floor | round | Frozen count |
|---|---:|---:|---:|---:|---:|
| narrow | 0.20 | 218.20 | 218 | 218 | 218 |
| narrow | 0.35 | 381.85 | 381 | 382 | 382 |
| regular | 0.20 | 255.40 | 255 | 255 | 255 |
| regular | 0.35 | 446.95 | 446 | 447 | 447 |

Therefore `218/382` and `255/447` are correct for the registered rule
`round(rho * |V_free|)`. The two high-density values would be wrong under a
floor rule.

## Split-contamination audit

- `warehouse_small_narrow_kiva` is explicitly the registered **development**
  map and is already present in the development artifacts, including the full
  17--26 matrix. It cannot be described as an independent validation topology.
  The two narrow-map density cells below are strictly **density robustness on
  the already-developed map**.
- `warehouse_small_kiva` is explicitly the registered **validation** map. No
  result artifact in either the local or AutoDL workspace names this map, so
  this is the only fresh map in the proposed four-condition check.
- The registered locked topology is `sortation_small_kiva.map`, not
  `sortation_small.map`. The latter has no `W`/`E` Kiva annotations and is
  rejected by `read_kiva_map`. Keep the whole sortation family out of
  development/validation if topology-family generalization remains a claim.
  In particular, do not use `sortation_small_kiva` for today's method choice.

There is also a pre-existing locked-test blocker that must be resolved by a
written amendment **before**, not after, locked seeds are opened:
`warehouse_60x100_kiva.map` starts with `typW octilW` and `hWight 60`, so the
current parser rejects it. The malformed file is identical locally and
remotely (SHA-256
`19a8ed65ce0d9c79650adf47299011e9b0843c93c27f68d46f3228a5aec0a049`).
This makes the valid held-out `sortation_small_kiva` map especially important
to preserve. Its local/remote SHA-256 is
`7a2ec55f0afc2e5969f15cdb19fefea47d2dbab2aafb51632d54e5e7f9c4e2e1`.

## Four-condition infrastructure sentinel

The sentinel uses only the already-open development seed 17. It is an
infrastructure/safety check, not evidence for method selection. Do not inspect
or rank throughput from the `warehouse_small_kiva` sentinel. Omit `--methods`
so each invocation automatically uses the frozen 13-method
`REGISTERED_METHODS` tuple. The development-only `random_memory_B25` candidate
is not part of this formal family.

Common shell setup on AutoDL:

```bash
cd /root/autodl-tmp/dai/research_workspace
DAI_PYTHON=/root/autodl-tmp/conda/envs/onlineggo39/bin/python
CKPT=/root/autodl-tmp/dai/research_workspace/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_10000.json
MAPDIR=/root/autodl-tmp/dai/research_workspace/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps
mkdir -p results/official_gate0/map_density_preflight
```

Run the following four invocations. Each has three workload cells, so
`--jobs 3` uses one process per workload. The four invocations can run in
parallel to occupy up to 12 CPU processes.

```bash
$DAI_PYTHON scripts/run_claim_aware_budgeted_validation.py \
  --workspace . --checkpoint "$CKPT" \
  --checkpoint-sha256 e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d \
  --checkpoint-params-sha256 6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac \
  --split development --seeds 17 \
  --workloads stationary abrupt recurrent \
  --map-path "$MAPDIR/warehouse_small_narrow_kiva.map" --agents 218 \
  --warmup-time 200 --horizon 600 --decision-window 20 --jobs 3 \
  --output results/official_gate0/map_density_preflight/narrow_r020_dev17_h600.json

$DAI_PYTHON scripts/run_claim_aware_budgeted_validation.py \
  --workspace . --checkpoint "$CKPT" \
  --checkpoint-sha256 e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d \
  --checkpoint-params-sha256 6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac \
  --split development --seeds 17 \
  --workloads stationary abrupt recurrent \
  --map-path "$MAPDIR/warehouse_small_narrow_kiva.map" --agents 382 \
  --warmup-time 200 --horizon 600 --decision-window 20 --jobs 3 \
  --output results/official_gate0/map_density_preflight/narrow_r035_dev17_h600.json

$DAI_PYTHON scripts/run_claim_aware_budgeted_validation.py \
  --workspace . --checkpoint "$CKPT" \
  --checkpoint-sha256 e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d \
  --checkpoint-params-sha256 6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac \
  --split development --seeds 17 \
  --workloads stationary abrupt recurrent \
  --map-path "$MAPDIR/warehouse_small_kiva.map" --agents 255 \
  --warmup-time 200 --horizon 600 --decision-window 20 --jobs 3 \
  --output results/official_gate0/map_density_preflight/regular_r020_dev17_h600.json

$DAI_PYTHON scripts/run_claim_aware_budgeted_validation.py \
  --workspace . --checkpoint "$CKPT" \
  --checkpoint-sha256 e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d \
  --checkpoint-params-sha256 6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac \
  --split development --seeds 17 \
  --workloads stationary abrupt recurrent \
  --map-path "$MAPDIR/warehouse_small_kiva.map" --agents 447 \
  --warmup-time 200 --horizon 600 --decision-window 20 --jobs 3 \
  --output results/official_gate0/map_density_preflight/regular_r035_dev17_h600.json
```

Let `M = len(REGISTERED_METHODS)` at launch time. Each invocation emits
`3M` runs and all four emit `12M` runs. For the frozen formal family `M=13`,
hence 39 runs per artifact and 156 runs total. Because `--methods` is omitted,
the command follows the frozen registry directly; verify that it reports 13
before launch.

The acceptance check is structural only: all four artifacts must be
`status=complete`, have exactly `3M` runs, pass the recorded safety and
cross-method tape/manifest invariants, obey publication/generator caps, and
have no simulator abort. Any throughput ranking from this sentinel is outside
its purpose.
