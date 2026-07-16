#!/usr/bin/env bash
# Source this file on the configured AutoDL instance before running Gate 0.

export DAI_WORKSPACE="${DAI_WORKSPACE:-/root/autodl-tmp/dai/research_workspace}"
export DAI_ONLINEGGO="${DAI_ONLINEGGO:-$DAI_WORKSPACE/external/OnlineGGO}"
export DAI_PYTHON="${DAI_PYTHON:-/root/autodl-tmp/conda/envs/onlineggo39/bin/python}"
export DAI_GATE0_BUILD="${DAI_GATE0_BUILD:-/root/autodl-tmp/dai/build/guided-pibt-gate0}"
export DAI_ARTIFACTS="${DAI_ARTIFACTS:-/root/autodl-tmp/artifacts}"

export PYTHONPATH="$DAI_WORKSPACE/src:$DAI_ONLINEGGO/CMAES${PYTHONPATH:+:$PYTHONPATH}"
export MPLBACKEND="${MPLBACKEND:-Agg}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export MALLOC_TRIM_THRESHOLD_="${MALLOC_TRIM_THRESHOLD_:-0}"
export CONDA_ENVS_PATH="${CONDA_ENVS_PATH:-/root/autodl-tmp/conda/envs}"
export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-/root/autodl-tmp/conda/pkgs}"

mkdir -p "$DAI_ARTIFACTS"
