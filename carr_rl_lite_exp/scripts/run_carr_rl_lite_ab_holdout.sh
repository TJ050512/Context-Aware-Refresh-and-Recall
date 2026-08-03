#!/usr/bin/env bash
set -euo pipefail
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
WORKSPACE=/root/autodl-tmp/dai/research_workspace
PYTHON=/root/autodl-tmp/conda/envs/onlineggo39/bin/python
CKPT=$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_20000.json
MAPDIR=$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps
POLICY=$WORKSPACE/results/carr_rl_lite/ab/a1.00_b0.02.json
OUT=$WORKSPACE/results/carr_rl_lite/ab_holdout
LOG=$WORKSPACE/logs/carr_rl_lite/ab_holdout
mkdir -p $OUT $LOG
run() {
  local label=$1 map=$2 agents=$3
  $PYTHON $WORKSPACE/scripts/run_carr_rl_lite_dev.py     --workspace $WORKSPACE --learned-policy-path $POLICY     --checkpoint $CKPT     --checkpoint-sha256 96cf69e18c4d1326bc42ec87be09341bf2c75038579161363473922448e27528     --checkpoint-params-sha256 03a14c7dbecee1b30cf73be6c4be9dc3da9ac176b462fa52542b4163aee52b7a     --split development --seeds 21 22 23 24 25 26     --workloads stationary abrupt recurrent     --methods context_memory_B25 context_learned_lite exact_even_B25     --warmup-time 200 --horizon 2000 --decision-window 20 --release-interval 110     --guard-suffix 4 --sigma 0.75 --context-match-threshold 0.05     --context-recall-margin 0.02 --context-min-score 0.10 --context-min-gap 6     --context-maintenance-age 25 --context-maintenance-stability 0.20     --jobs 30 --fresh-process-per-arm     --map-path $MAPDIR/$map --agents $agents     --output $OUT/$label.json > $LOG/$label.log 2>&1 &
  echo $! >> $LOG/pids
}
run narrow_r020 warehouse_small_narrow_kiva.map 218
run narrow_r035 warehouse_small_narrow_kiva.map 382
run regular_r020 warehouse_small_kiva.map 255
run regular_r035 warehouse_small_kiva.map 447
wait
echo HOLDOUT_DONE
