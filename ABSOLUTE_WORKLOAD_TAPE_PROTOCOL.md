# Absolute-time exogenous workload tape (claim-bearing protocol)

## Scope and conservative semantic choice

The formal non-stationary comparison uses
`dai.kiva-absolute-release-tape/v1`. For every agent, the complete ordered
sequence of `[flattened_goal_location, release_timestep]` records is copied
into C++ before simulator timestep zero. Task identity is the agent-major
contiguous offset plus the per-agent tape index. No task goal or release time
is sampled during a rollout.

This is an **arrival queue**, not a completion-driven goal generator. A faster
method may assign and complete a longer prefix, but at any absolute simulator
time all methods have released exactly the same prefix of exactly the same
manifest. That difference in consumed prefix is an outcome of the treatment.

## Decision-epoch semantics

- At initialization, all records with `release_timestep == 0` are released
  before the first planner call.
- For `t > 0`, the simulator first executes the move ending at `t` and records
  completions, then releases all records whose absolute release time is `t`.
  Those tasks are available to the planner decision made at `t` (the action
  whose move ends at `t + 1`).
- Released records enter an immutable per-agent FIFO backlog. The simulator
  reveals/assigns from that backlog until `num_tasks_reveal` visible tasks are
  present. Release is exogenous; reveal and completion can be method-dependent.
- Multiple records may share a release timestep (a burst). Release times must
  be nondecreasing within each agent's tape.
- Warmup uses the same absolute clock. A release at `t=10` means simulator time
  10, irrespective of whether 10 lies in warmup or the scored interval.

Kiva goals must alternate according to the existing simulator contract:
`W -> E` and `E/. -> W`. The manifest fixes agent assignment; no online task
allocator is involved.

## Idle agents

Queued workloads can leave an agent temporarily without a released task. The
existing planner requires a target for every agent, so C++ gives an idle agent
an internal holding target equal to its current location. This is not a task:
it is excluded from `goal_loc_arr`, task observations, events, service cost,
and throughput. `curr_task_active` distinguishes real goals from holding
targets. The simulator runs to the fixed horizon even if all agents are idle.

## Identity and verification

The manifest SHA-256 covers canonical JSON containing only:

1. schema version;
2. flattened start locations;
3. every per-agent `[goal, release_timestep]` record in order.

C++ independently computes FNV-1a64 over the same content using explicit
little-endian unsigned-64 encoding. The trace reports both identities, plus
per-agent `released_prefix_lengths`, `assigned_prefix_lengths`, and
`completed_prefix_lengths`.

Python reconstructs every event and enforces:

- `released_prefix(t)` equals the number of manifest records with
  `release_timestep <= t` (not merely a monotone counter);
- each `released` event occurs at its exact registered absolute time;
- `completed <= assigned <= released <= tape length` per agent;
- event task ID and goal equal the corresponding manifest record;
- `online_workload_rng_draws == 0`;
- starts, SHA-256, FNV-1a64, schema, mode, and release semantics all match.

The simulator trace schema is bumped to `dai.onlineggo.trace/v3` because v3
adds `released` events and `curr_task_active`.

## Offline phase-shift generator

`src/dai_lmapf/absolute_workload.py` provides a stateless offline generator.
The caller supplies starts, an absolute release schedule, phase boundaries,
and one Kiva endpoint hotspot per phase. Goals are sampled with keyed SHA-256
quantiles, so generation order and one agent's task count cannot perturb any
other agent. The produced tape is still the sole simulator authority; phase
metadata is descriptive and cannot trigger online sampling.

Example (phase centers are flattened Kiva `E` locations):

```bash
PYTHONPATH=src python scripts/generate_absolute_workload_tape.py \
  --map /path/to/warehouse_small_narrow_kiva.map \
  --starts-json /path/to/pre_generated_starts.json \
  --release-timesteps 0,40,80,120,160,200,240,280,320,360,400,440,480,520,560 \
  --phase-starts 0,160,320,480 \
  --phase-centers 230,260,1450,1480 \
  --task-seed 12345 --sigma 0.75 --horizon 600 \
  --output manifests/seed_001.absolute-tape.json
```

The center IDs above are illustrative only; the generator rejects centers that
are not endpoints on the selected map. Starts must come from the same episode
seed used by C++, for example from the existing saturated tape helper.

## Residual limitations

- This implementation is Kiva-specific and models one reach-goal service per
  record. It does not model pickup/drop-off pairs, service dwell time, task
  cancellation, reassignment, or a global unassigned job market.
- Starts are still regenerated from the episode seed by C++ and must equal the
  manifest. Planner priority randomness remains separately seeded; the
  no-online-RNG guarantee applies to workload contents and arrivals.
- A finite tape must cover the registered horizon and intended arrival rate.
  Once all records are completed, agents correctly idle until the horizon.
- Public baselines that cannot consume the same per-agent release tape are
  non-aligned references and cannot support paired SOTA/significance claims.
- Formal experiments must archive the complete tape artifact and hash, not
  only the generator parameters or seed.

## Local and remote verification

Pure Python/unit validation:

```bash
cd /path/to/research_workspace
PYTHONPATH=src python -m unittest tests.test_absolute_workload \
  tests.test_online_ggo_fixed_tape
```

After rebuilding the instrumented Linux simulator, run:

```bash
cd /path/to/research_workspace
$DAI_PYTHON tests/run_online_ggo_absolute_tape_integration.py
$DAI_PYTHON tests/run_online_ggo_fixed_tape_integration.py
```

Both sentinels must pass. The second prevents the new queue mode from
regressing the saturated Gate-P0 path.
