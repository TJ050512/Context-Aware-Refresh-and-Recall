#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=autodl_env.sh
source "$SCRIPT_DIR/autodl_env.sh"

cd "$DAI_WORKSPACE"

"$DAI_PYTHON" -m dai_lmapf.online_ggo_preflight \
  --repo "$DAI_ONLINEGGO" \
  --output "$DAI_ARTIFACTS/online_ggo_preflight_deterministic_build.json" \
  --strict

"$DAI_PYTHON" -m pytest -q

"$DAI_PYTHON" scripts/gate0_runtime_smoke.py \
  --agents 400 --seed 17 --warmup-time 50 --interval 50 \
  --simulation-time 150 \
  --output "$DAI_ARTIFACTS/gate0_runtime_stress_400a_seed17_200t_a.json"

"$DAI_PYTHON" scripts/gate0_runtime_smoke.py \
  --agents 400 --seed 17 --warmup-time 50 --interval 50 \
  --simulation-time 150 \
  --output "$DAI_ARTIFACTS/gate0_runtime_stress_400a_seed17_200t_b.json"

"$DAI_PYTHON" scripts/compare_gate0_replay.py \
  "$DAI_ARTIFACTS/gate0_runtime_stress_400a_seed17_200t_a.json" \
  "$DAI_ARTIFACTS/gate0_runtime_stress_400a_seed17_200t_b.json" \
  --output "$DAI_ARTIFACTS/gate0_replay_comparison_400a_seed17_200t.json"
