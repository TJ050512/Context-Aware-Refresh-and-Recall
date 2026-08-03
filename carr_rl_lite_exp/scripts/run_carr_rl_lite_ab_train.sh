#!/usr/bin/env bash
set -euo pipefail
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
WORKSPACE=/root/autodl-tmp/dai/research_workspace
PYTHON=/root/autodl-tmp/conda/envs/onlineggo39/bin/python
CKPT=$WORKSPACE/external/OnlineGGO/CMAES/logs/dai10k_resume_seed17_from_2k/checkpoints/optimal_update_model_20000.json
MAPDIR=$WORKSPACE/external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps
OUT=$WORKSPACE/results/carr_rl_lite/ab_train
LOG=$WORKSPACE/logs/carr_rl_lite/ab_train
mkdir -p $OUT $LOG
# 6 candidate (alpha,beta) policies
CANDS=(a1.00_b0.00 a0.95_b0.00 a0.90_b0.00 a1.00_b-0.02 a1.00_b0.02 a1.05_b0.00)
# 2 training scenarios
declare -A MAPS=( [narrow_r020]='warehouse_small_narrow_kiva.map 218' [regular_r020]='warehouse_small_kiva.map 255' )
for cand in "${CANDS[@]}"; do
  for scen in narrow_r020 regular_r020; do
    read map agents <<< "${MAPS[$scen]}"
    $PYTHON $WORKSPACE/scripts/run_carr_rl_lite_dev.py       --workspace $WORKSPACE --learned-policy-path $WORKSPACE/results/carr_rl_lite/ab/$cand.json       --checkpoint $CKPT       --checkpoint-sha256 96cf69e18c4d1326bc42ec87be09341bf2c75038579161363473922448e27528       --checkpoint-params-sha256 03a14c7dbecee1b30cf73be6c4be9dc3da9ac176b462fa52542b4163aee52b7a       --split development --seeds 17 18 19 20 --workloads stationary abrupt       --methods context_learned_lite exact_even_B25       --warmup-time 200 --horizon 2000 --decision-window 20 --release-interval 110       --guard-suffix 4 --sigma 0.75 --context-match-threshold 0.05       --context-recall-margin 0.02 --context-min-score 0.10 --context-min-gap 6       --context-maintenance-age 25 --context-maintenance-stability 0.20       --jobs 24 --fresh-process-per-arm       --map-path $MAPDIR/$map --agents $agents       --output $OUT/${cand}__${scen}.json > $LOG/${cand}__${scen}.log 2>&1 &
  done
done
wait
echo TRAIN_DONE
