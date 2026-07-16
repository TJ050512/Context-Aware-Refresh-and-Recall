# Known validity issues in the coursework baseline

Status: confirmed by code inspection and targeted local tests on 2026-07-13.

These are not cosmetic limitations. They must be resolved before using the baseline to support a paper claim.

1. **The current “RL-adaptive” router is not online RL.** It exhaustively evaluates fixed scales for each density bucket and stores the best sample mean in a lookup table. The context is only the number of agents and stays constant within an episode.
2. **A tuned fixed policy can beat the current lookup policy.** A small four-seed audit found that fixed `scale=1` had better mean throughput across the five tested densities than the reported density lookup. A full paired evaluation is still required, but the current superiority claim is already unsupported.
3. **The PIBT-lite executor can produce a vertex collision.** Failed recursive displacement does not transactionally roll back all reservations. A bottleneck stress test reproduced two agents occupying `(4, 11)` at the same step.
4. **Task generation permits zero-distance tasks and repeated goals.** The measured zero-distance assignment rate rose from roughly 14% at 8 agents to 32% at 24 agents, mechanically inflating dense-setting throughput.
5. **The workload is stationary and map-specific.** All main experiments use one two-corridor topology, one top-biased task generator, and the same density grid for selection and evaluation. Training and evaluation seeds differ, but the distributions do not.
6. **The experiment is a saturated backlog, not a time-varying arrival process.** Tasks are pre-generated and replenished upon completion; `created_step` is not used to model arrivals, bursts, or workload shifts.
7. **Congestion allocation uses stale paths.** Planned paths are not consistently trimmed or updated after execution and rerouting, so the allocation congestion estimate can disagree with the actual traffic.
8. **The “corridor” detector is not map-invariant.** A degree-based rule marks room corners as corridors and labels most free cells in the current warehouse map as corridor cells.
9. **Lifelong deadlock detection is disabled.** The lifelong result always reports `deadlocked=False`; priority tie-breaking can also introduce stable agent-ID bias.
10. **The reported wait-reduction percentage uses the wrong denominator.** The conventional reductions are approximately 52.1%–63.5%, not 108%–174%.
11. **Eight seeds are insufficient for the observed heavy-tailed outcomes.** The paper protocol must use paired scenario manifests, at least 30 test seeds where affordable, robust bootstrap/permutation inference, and multiplicity correction.

## Required correctness gate

- Replace the custom executor with a reference PIBT implementation or add transactional rollback.
- Assert unique vertices and absence of edge swaps at every step.
- Exclude goals equal to current positions; define endpoint capacity and duplicate-goal semantics explicitly.
- Add a real arrival schedule, task IDs, release times, and service-time accounting.
- Separate map, workload, density, task, and policy seeds in an immutable scenario manifest.
- Re-run at least 6 map layouts × 100 seeds × 1,000 steps with zero invariant violations.
