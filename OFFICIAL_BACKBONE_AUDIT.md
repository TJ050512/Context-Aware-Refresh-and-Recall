# Official OnlineGGO backbone audit

Date: 2026-07-13

Pinned source: `external/OnlineGGO` at commit
`ff6d830e2fd5bf85ccbb72eaec0fb8df1cf1c256`.

## Decisive semantic finding

The official `[p-on]+GPIBT` interface does **not** globally recompute guide
paths when Python supplies new edge weights.

- `period_on_sim.cpp:19-27` contains comments about clearing/recomputing
  heuristics, but the implementation only delegates to
  `BaseSystem::update_gg_and_step`.
- `CompetitionSystem.cpp:192-197` checks `H*W*4` and assigns
  `env->map_weights`.
- `CompetitionSystem.cpp:269-337` then advances the normal simulation window;
  it performs no global cache invalidation or guide-path repair.
- `MAPFPlanner.cpp:169-174` calls `remove_traj` and `update_traj` only when an
  agent's task changes.
- `traffic_mapf/search.cpp:573-595` reads the new weights when a new weighted
  A* guide path is actually generated.
- The default `trafficMAPF_on` module is compiled with `GUIDANCE_LNS=OFF`, so
  periodic LNS does not propagate the change either.

Consequently, an OnlineGGO weight update has future-only semantics: it affects
newly generated guide paths while already active agents retain old paths and
distance-to-path guidance.

## Correct refresh/reuse contract

| Operation | Generator called | Simulator advances | Existing guide paths repaired |
|---|---:|---:|---:|
| Reuse cached action | No | Yes | No |
| Official lazy update | Yes | Yes | No |
| Selective repair extension | Yes | Yes | Selected agents only |
| All-agent repair oracle | Yes | Yes | All eligible agents |

For official lazy reuse, Python must call `env.step(last_raw_action)`. Skipping
`step` would also skip agent motion, task assignment, observation construction,
and reward. Reuse saves only generator work; it does not save PIBT execution or
new-task A* calls.

The raw generator action must be cached. Do not cache weights returned from the
private normalized simulator path and send them through `env.step` again,
because the environment min-max normalizes each raw action.

## Direction-order hazard

`period_on_sim` consumes flattened per-cell weights in `R,D,L,U` order:
`traffic_mapf/utils.cpp:7-15` maps direction indices 0,1,2,3 to right, down,
left, up. The Python observation helper in
`trafficflow_online_env.py:21-23` maps motion channels as `R,U,L,D`.

The adapter therefore pins generator **output** to `R,D,L,U` and refuses any
other declared order. Before main experiments, an asymmetric-map sentinel test
must confirm the end-to-end mapping. Observation channels must be documented
separately; no silent permutation is allowed.

## Implemented adapter

`src/dai_lmapf/online_ggo_adapter.py` provides a dependency-free wrapper around
the official Gymnasium-style environment:

- validates finite `[4,H,W]` actions;
- enforces the `R,D,L,U` output contract;
- keeps immutable defensive copies and stable action hashes;
- calls the generator only on refresh;
- calls the simulator on both refresh and reuse;
- separates generator and simulator wall time;
- faults the run after a simulator exception because C++ state may have
  advanced and cannot be rolled back safely.

This adapter reproduces official lazy semantics. It does not claim to skip
guidance application or planner computation.

The pinned checkout also has an uncompiled research-instrumentation diff with
strict window/task/planner schemas, the applied normalized-weight hash, build
flags, internal graph revisions, and direct INIT_PP/task-change guide-path
construction events. This avoids using assignment time as a treatment proxy:
a queued task may be revealed under one version but have its path built under
another. The diff is not compiled or validated on the current Mac and must pass
the Linux semantic and replay gate before use.

The adapter's stable hash covers the raw generator action; the instrumentation
keeps it separate from a hash of the post-mask, post-normalization vector sent
to C++. The latter is the candidate treatment identifier, pending compilation
and an asymmetric RDLU sentinel.

## Determinism and attribution hazards

- The Python `reset(seed=...)` path does not propagate the supplied seed, and
  planner initialization shuffles priorities with `std::random_device()`.
- Online task generation depends on completion time, so different scheduling
  methods can receive different future tasks even with the same nominal seed.
- A task's assignment version is not necessarily its guide-path construction
  version, especially when more than one task is revealed per agent.
- Version-level service-time means confound version with time, workload phase,
  task difficulty, and terminal right censoring. They are diagnostic feedback,
  not causal treatment estimates.

The primary experiment must therefore use fixed starts and an exogenous task
tape, trace route construction directly, and estimate schedule effects from
paired episode outcomes.

## Current machine preflight

The local host is macOS arm64 with Python 3.13. The official reference path is
Ubuntu 20.04, x86_64, Python 3.9, CMake, Boost 1.71, and Singularity. The shallow
checkout also lacks populated Eigen, MiniDNN, and pybind11 submodules and has no
compiled `period_on_sim` module. See
`results/online_ggo_preflight_macos.json`.

The official repository also contains no trained OnlineGGO checkpoint. A final
comparison needs either an author-provided checkpoint or a fresh CMA-ES run;
random CNN parameters are not an OnlineGGO baseline.

## Linux bring-up sequence

On an Ubuntu x86_64 machine:

```bash
cd external/OnlineGGO
git submodule set-url third_party/eigen https://github.com/PX4/eigen.git
git submodule set-url third_party/MiniDNN https://github.com/yixuan/MiniDNN.git
git submodule set-url third_party/pybind11 https://github.com/pybind/pybind11.git
git submodule update --init --recursive
```

Then follow the pinned repository's Singularity build, or reproduce its Python
3.9/C++17/Boost 1.71 build environment. Before any method comparison:

1. Run the preflight module and archive its JSON.
2. Verify uniform weights on a tiny map.
3. Run the asymmetric RDLU sentinel test.
4. Archive compiler flags/binary hash and assert `GUIDANCE_LNS=OFF`.
5. Hash the normalized weights received by C++ and trace guide-path builds.
6. Replace implicit randomness with fixed starts and an exogenous task tape;
   require deterministic cached-action replay.
7. Validate non-overlapping trace windows, including a short final window and
   a task event exactly on a publication boundary.
8. Measure generator, guide-path construction, PIBT, serialization, and
   end-to-end time separately where the source permits it.
9. Only after these checks pass, run Gate 0B from
   `configs/guidance_versioning_gate0.json`.
