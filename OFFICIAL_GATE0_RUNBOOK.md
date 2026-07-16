# OnlineGGO Gate 0 runbook

Date: 2026-07-13

This gate validates semantics and replay before measuring method quality. A
passing local smoke experiment is not a substitute.

## Machine

- Ubuntu 20.04/22.04 x86_64;
- Python 3.9 and CMake;
- Boost 1.71-compatible headers, Eigen, MiniDNN, and pybind11;
- at least 16 CPU cores and 32 GB RAM for the first simulator gate;
- a larger multicore allocation for fresh CMA-ES training. A GPU is optional
  for simulator bring-up but useful if the chosen generator training path uses
  PyTorch acceleration.

## Frozen inputs

- source revision: `ff6d830e2fd5bf85ccbb72eaec0fb8df1cf1c256`;
- protocol: `configs/guidance_versioning_gate0.json`;
- primary simulator: `trafficMAPF_on` / GPIBT;
- required build flags: `GUIDANCE=ON`, `GUIDANCE_LNS=OFF`,
  `FLOW_GUIDANCE=OFF`, `INIT_PP=ON`, `RELAX=100`, `OBJECTIVE=5`;
- generator checkpoint hash, task-generator seed/tape hash, map hash, and every
  compiled `.so` hash must be recorded with each run.

## Bring-up

From `external/OnlineGGO`:

```bash
git rev-parse HEAD
git submodule set-url third_party/eigen https://github.com/PX4/eigen.git
git submodule set-url third_party/MiniDNN https://github.com/yixuan/MiniDNN.git
git submodule set-url third_party/pybind11 https://github.com/pybind/pybind11.git
git submodule update --init --recursive
```

Reproduce the pinned repository's Python 3.9/Singularity build, using the
`trafficMAPF_on` flags above. Archive:

```bash
cmake --version
python3.9 --version
sha256sum CMAES/simulators/trafficMAPF_on/*.so
```

Then run the workspace preflight:

```bash
cd /path/to/research_workspace
PYTHONPATH=src python3.9 -m dai_lmapf.online_ggo_preflight \
  --repo external/OnlineGGO \
  --output results/online_ggo_preflight_linux.json
```

## Gate 0A: semantic and replay sentinels

All must pass before schedule comparisons:

1. Uniform graph: raw-action hash, applied normalized-weight hash, and C++
   internal revision agree across reuse windows.
2. Asymmetric map: perturb only one directional channel and verify end-to-end
   RDLU movement cost at a known cell.
3. Publication boundary: a guide path constructed on the first planning call
   after publication carries the new version; a task merely revealed at the
   previous window end is not mislabeled.
4. INIT_PP: deferred initial guide paths are logged only when actually built.
5. Replay: fixed build, start state, random source, task-generator tape, raw
   actions, and method produce identical traces on two runs.
6. Window trace: no duplicate/missing event IDs, exact final partial window,
   one planner-time record per executed step, and zero safety violations.

Any failure invalidates downstream throughput comparisons.

## Gate 0B: schedule headroom

Use 10 development seeds on the frozen warehouse configuration. Run `never`,
`always`, periods 20/50/100, and an oracle-shift diagnostic. Starts and the
exogenous random source/tape are paired; record the realized task sequence for
every method because task completion can alter future assignments.

Proceed to controller development only if a non-oracle schedule beats `never`
under dynamic demand and there remains reproducible headroom relative to the
best fixed schedule or oracle. Otherwise the current publication-control paper
is a No-Go.

## Evidence boundary

The 3,336 local smoke runs can motivate Gate 0, but only compiled official
OnlineGGO/GPIBT runs on public maps can enter the main empirical claim. Route
cohort service summaries are diagnostic feedback; paired episode throughput
and recovery are the causal endpoints.
