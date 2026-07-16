import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_same_call_confirmation_v1.py"
SPEC = importlib.util.spec_from_file_location("same_call_analysis", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timeline(method: str, root_seed: int):
    exact = {
        "bootstrap_only": [],
        "exact_even_G4": MODULE.exact_schedule(4),
        "exact_even_G5": MODULE.exact_schedule(5),
        "random_G5": MODULE.random_g5_schedule(root_seed),
        "exact_even_B25": MODULE.exact_schedule(25),
    }
    if method in exact:
        generations = set(exact[method])
        reactivations = set()
    elif method == "js_cap_G5":
        generations = {20, 40, 60, 80}
        reactivations = set()
    elif method == "context_no_reactivation_B25":
        generations = {20, 40, 60, 80}
        reactivations = set()
    else:
        generations = {20, 40, 60, 80}
        reactivations = {90}
    rows = [
        {
            "decision_index": 0,
            "scored_timestep": 0,
            "absolute_timestep": 200,
            "requested": True,
            "accepted": True,
            "requested_operation": "bootstrap_generate",
            "executed_operation": "bootstrap_generate",
            "charged_to_post_bootstrap_budget": False,
            "charged_to_post_bootstrap_switch_cap": False,
            "charged_to_post_bootstrap_generation_cap": False,
            "charged_to_generator_budget": False,
            "guidance_version_before_decision": 0,
            "guidance_version_installed_for_window": 1,
            "active_generation_id_after": 1,
        }
    ]
    version = 1
    active_generation = 1
    next_generation = 2
    for decision in range(1, 100):
        operation = (
            "generate"
            if decision in generations
            else "reactivate"
            if decision in reactivations
            else "hold"
        )
        accepted = operation != "hold"
        before = version
        target = None
        if accepted:
            version += 1
        if operation == "generate":
            active_generation = next_generation
            next_generation += 1
        elif operation == "reactivate":
            target = 1
            active_generation = target
        rows.append(
            {
                "decision_index": decision,
                "scored_timestep": decision * 20,
                "absolute_timestep": 200 + decision * 20,
                "requested": accepted,
                "accepted": accepted,
                "requested_operation": operation,
                "executed_operation": operation,
                "charged_to_post_bootstrap_budget": accepted,
                "charged_to_post_bootstrap_switch_cap": accepted,
                "charged_to_post_bootstrap_generation_cap": operation == "generate",
                "charged_to_generator_budget": operation == "generate",
                "target_generation_id": target,
                "guidance_version_before_decision": before,
                "guidance_version_installed_for_window": version,
                "active_generation_id_after": active_generation,
            }
        )
    return rows


def _budget(method: str, timeline):
    post = timeline[1:]
    generations = sum(row["executed_operation"] == "generate" for row in post)
    reactivations = sum(row["executed_operation"] == "reactivate" for row in post)
    publications = generations + reactivations
    exact_quota = method in {
        "bootstrap_only",
        "exact_even_G4",
        "exact_even_G5",
        "random_G5",
        "exact_even_B25",
    }
    registered = {
        "bootstrap_only": 0,
        "exact_even_G4": 4,
        "exact_even_G5": 5,
        "random_G5": 5,
        "js_cap_G5": 5,
        "context_no_reactivation_B25": 25,
        "context_memory_B25": 25,
        "exact_even_B25": 25,
    }[method]
    total_cap = 1 + (5 if method in {"exact_even_G5", "random_G5", "js_cap_G5"} else 4 if method == "exact_even_G4" else 25 if method in {"context_no_reactivation_B25", "context_memory_B25", "exact_even_B25"} else 0)
    return {
        "mandatory_bootstrap_calls": 1,
        "post_bootstrap_budget": registered,
        "effective_guidance_switch_cap": registered,
        "post_bootstrap_generation_cap": registered,
        "total_generator_call_cap": total_cap,
        "post_bootstrap_publication_count": publications,
        "post_bootstrap_generation_count": generations,
        "post_bootstrap_reactivation_count": reactivations,
        "effective_guidance_switch_count": publications,
        "total_generator_calls": 1 + generations,
        "generator_call_conservation_satisfied": True,
        "switch_operation_partition_satisfied": True,
        "budget_violation_attempts": 0,
        "budget_semantics": "exact" if exact_quota else "at_most",
        "cap_satisfied": True,
        "switch_cap_satisfied": True,
        "generation_cap_satisfied": True,
        "total_generator_call_cap_satisfied": True,
        "exact_quota_required": exact_quota,
        "exact_quota_satisfied": True,
    }


def _guidance_hash(kind: str, generation_id: int) -> str:
    return hashlib.sha256(f"{kind}:{generation_id}".encode()).hexdigest()


def _windows(timeline, final_tasks: int, agents: int):
    rows = []
    quotient, remainder = divmod(final_tasks, 100)
    cumulative = 0
    for index, publication in enumerate(timeline):
        reward = quotient + (1 if index < remainder else 0)
        cumulative += reward
        generation_id = publication["active_generation_id_after"]
        rows.append(
            {
                "decision_index": index,
                "window_start_timestep": 200 + 20 * index,
                "window_end_timestep": 220 + 20 * index,
                "reward": float(reward),
                "num_task_finished": cumulative,
                "assigned_prefix_total": agents + cumulative + agents,
                "completed_prefix_total": agents + cumulative,
                "generation_id": generation_id,
                "installation_version": publication[
                    "guidance_version_installed_for_window"
                ],
                "guidance_version": publication[
                    "guidance_version_installed_for_window"
                ],
                "guidance_sha256": _guidance_hash("raw", generation_id),
                "applied_guidance_sha256": _guidance_hash(
                    "applied", generation_id
                ),
                "guidance_operation": (
                    "hold" if index == 0 else publication["executed_operation"]
                ),
                "guidance_switched_post_bootstrap": (
                    index > 0 and publication["accepted"]
                ),
                "refreshed_post_bootstrap": (
                    index > 0 and publication["executed_operation"] == "generate"
                ),
            }
        )
    return rows


def _distribute(total: int, count: int) -> list[int]:
    quotient, remainder = divmod(total, count)
    return [quotient + (index < remainder) for index in range(count)]


def _guidance_catalog(method: str, timeline):
    if method not in {MODULE.FOCAL, MODULE.NO_REACTIVATION}:
        return []
    decisions = [0] + [
        row["decision_index"]
        for row in timeline[1:]
        if row["executed_operation"] == "generate"
    ]
    rows = []
    for generation_id, decision in enumerate(decisions, 1):
        context = [generation_id / 100.0] * 16
        rows.append(
            {
                "generation_id": generation_id,
                "generated_at_decision": decision,
                "source": "bootstrap" if generation_id == 1 else "generated",
                "context": context,
                "context_sha256": MODULE._canonical_sha256(context),
                "raw_guidance_sha256": _guidance_hash("raw", generation_id),
                "applied_guidance_sha256": _guidance_hash(
                    "applied", generation_id
                ),
            }
        )
    return rows


def _task_offset(method: str) -> int:
    return {
        "bootstrap_only": 0,
        "exact_even_G4": 20,
        "exact_even_G5": 25,
        "random_G5": 22,
        "js_cap_G5": 18,
        "context_no_reactivation_B25": 15,
        "context_memory_B25": 50,
        "exact_even_B25": 51,
    }[method]


def _make_run(
    *, scenario_id: str, method: str, root_seed: int, workload: str, pid: int
):
    timeline = _timeline(method, root_seed)
    budget = _budget(method, timeline)
    scenario_rank = list(MODULE.SCENARIOS).index(scenario_id)
    root_rank = MODULE.ROOTS.index(root_seed)
    workload_rank = MODULE.WORKLOADS.index(workload)
    base = 1000 + 3 * scenario_rank + root_rank + workload_rank
    final_tasks = base + _task_offset(method)
    agents = MODULE.SCENARIOS[scenario_id]["agents"]
    map_id = f"map-{scenario_id}"
    manifest_sha = hashlib.sha256(
        f"{scenario_id}:{root_seed}:{workload}".encode()
    ).hexdigest()
    identity = {
        "mode": "absolute_release_queue_per_agent",
        "schema_version": "dai.kiva-absolute-release-tape/v1",
        "manifest_sha256": manifest_sha,
        "content_fnv1a64": f"{root_seed:016x}",
        "start_locations": list(range(agents)),
        "per_agent_lengths": [100] * agents,
        "total_tasks": 100 * agents,
    }
    pairing = f"{map_id}:{workload}:{root_seed}:{manifest_sha[:16]}"
    if method in {
        "bootstrap_only",
        "exact_even_G4",
        "exact_even_G5",
        "random_G5",
        "exact_even_B25",
    }:
        declared = [
            row["decision_index"] for row in timeline[1:] if row["accepted"]
        ]
    else:
        declared = None
    completed = _distribute(agents + final_tasks, agents)
    assigned = [value + 1 for value in completed]
    released = [value + 1 for value in assigned]
    run_uuid = str(uuid.UUID(int=pid))
    process_start_ns = pid * 1000 + 500
    return {
        "method": method,
        "seed": root_seed,
        "root_seed": root_seed,
        "split": MODULE.SPLIT,
        "evidence_class": MODULE.SPLIT,
        "workload": workload,
        "map_id": map_id,
        "map_path": f"/synthetic/{map_id}.map",
        "num_task_finished": final_tasks,
        "throughput_per_timestep": final_tasks / 2000.0,
        "scored_horizon": 2000,
        "decision_window": 20,
        "window_count": 100,
        "mandatory_bootstrap_calls": 1,
        "post_bootstrap_publication_count": budget["post_bootstrap_publication_count"],
        "post_bootstrap_generation_count": budget["post_bootstrap_generation_count"],
        "post_bootstrap_reactivation_count": budget["post_bootstrap_reactivation_count"],
        "effective_guidance_switch_count": budget["effective_guidance_switch_count"],
        "publication_budget": budget["post_bootstrap_budget"],
        "budget_violation_count": 0,
        "budget": budget,
        "generator_calls": budget["total_generator_calls"],
        "publication_timeline": timeline,
        "precommitted_post_bootstrap_schedule": declared,
        "windows": _windows(timeline, final_tasks, agents),
        "guidance_catalog": _guidance_catalog(method, timeline),
        "final_task_tape_prefixes": {
            "released_prefix_lengths": released,
            "assigned_prefix_lengths": assigned,
            "completed_prefix_lengths": completed,
            "all_released": False,
            "all_completed": False,
        },
        "safety": {
            "passed": True,
            "collision_count": 0,
            "edge_swap_count": 0,
            "invalid_move_count": 0,
            "endpoint_mismatch_count": 0,
            "route_trace_invalid_count": 0,
            "planner_timeout_count": 0,
        },
        "collisions": 0,
        "edge_swaps": 0,
        "invalid_moves": 0,
        "planner_timeouts": 0,
        "invariants": {
            "passed": True,
            "online_workload_rng_draws": 0,
            "tape_not_exhausted": True,
            "reward_sum_matches_completed": True,
            "unexposed_completions_excluded_from_cohorts": True,
        },
        "cohort_attribution_audit": {
            "route_exposed_completion_count": 100,
            "unexposed_zero_route_completion_count": 1,
            "unexposed_zero_route_completions_excluded": True,
            "route_build_reason_counts": {
                "init_pp": 1,
                "task_change": 100,
            },
        },
        "route_build_reason_counts": {
            "init_pp": 1,
            "task_change": 100,
        },
        "manifest_id": pairing,
        "task_tape_identity": identity,
        "reset_causal_fingerprint": hashlib.sha256(
            f"reset:{pairing}".encode()
        ).hexdigest(),
        "release_projection_fingerprint": hashlib.sha256(
            f"release:{pairing}".encode()
        ).hexdigest(),
        "distribution_update_fingerprint": hashlib.sha256(
            f"distribution:{pairing}".encode()
        ).hexdigest(),
        "workload_arrival": {
            "name": "dai_claim_absolute_workload/v1",
            "root_seed": root_seed,
            "workload": workload,
            "warmup_time": 200,
            "scored_horizon": 2000,
            "release_interval_per_agent": 110,
            "guard_suffix_tasks_per_agent": 4,
            "schedule": "deterministic_agent_stagger/v1",
            "task_seed": root_seed + 123,
        },
        "execution_process_id": pid,
        "execution_parent_process_id": 5000 + scenario_rank,
        "execution_host": "synthetic-host",
        "execution_process_start_ns": process_start_ns,
        "run_uuid": run_uuid,
    }


def _clone_run(artifacts, artifact_index, run_index):
    result = list(artifacts)
    artifact = dict(result[artifact_index])
    artifact["runs"] = list(artifact["runs"])
    artifact["runs"][run_index] = dict(artifact["runs"][run_index])
    result[artifact_index] = artifact
    return result, artifact["runs"][run_index]


def _artifact_protocol(agents: int):
    protocol = dict(MODULE.ARTIFACT_PROTOCOL_CORE)
    protocol.update(
        {
            "agents": agents,
            "exact_even_G4": {
                "development_only": True,
                "post_bootstrap_generation_and_switch_quota": 4,
                "mandatory_bootstrap_counts_toward_post_quota": False,
                "total_generator_calls": 5,
                "quota_rule": "exact_even_over_99_eligible_decisions",
            },
            "exact_even_G5": {
                "development_only": True,
                "post_bootstrap_generation_and_switch_quota": 5,
                "mandatory_bootstrap_counts_toward_post_quota": False,
                "total_generator_calls": 6,
                "quota_rule": "exact_even_over_99_eligible_decisions",
            },
            "random_G5": {
                "development_only": True,
                "post_bootstrap_generation_and_switch_quota": 5,
                "mandatory_bootstrap_counts_toward_post_quota": False,
                "total_generator_calls": 6,
                "schedule_rng": "root-keyed local publication-policy stream",
                "quota_rule": "exact_random_without_replacement",
            },
            "js_cap_G5": {
                "development_only": True,
                "score": "active_goal_js_since_last_publication",
                "score_quantile": 0.75,
                "min_gap_windows": 2,
                "minimum_effect_windows": 3,
                "post_bootstrap_generation_and_switch_cap": 5,
                "total_generator_call_cap": 6,
                "quota_rule": "at_most_G5_with_no_catch_up_or_forced_fill",
            },
            MODULE.FOCAL: {
                "actions": ["hold", "reactivate", "generate"],
                "score": "release_only_4x4_fast2_vs_prior6_js",
                "score_quantile": 0.75,
                "absolute_score_gate": 0.10,
                "active_route_fraction_gate": 0.5,
                "min_gap_windows": 6,
                "maintenance_age_windows": 25,
                "maintenance_stability_gate": 0.20,
                "minimum_effect_windows": 3,
                "context": "causal_active_goal_4x4",
                "recall_threshold": 0.05,
                "recall_margin": 0.02,
                "quota_rule": "at_most_B25_for_both_switches_and_generations",
            },
            MODULE.NO_REACTIVATION: {
                "development_only": True,
                "base_controller": MODULE.FOCAL,
                "actions": ["hold", "generate"],
                "forbidden_action": "reactivate",
                "score": "release_only_4x4_fast2_vs_prior6_js",
                "score_quantile": 0.75,
                "absolute_score_gate": 0.10,
                "active_route_fraction_gate": 0.5,
                "min_gap_windows": 6,
                "maintenance_age_windows": 25,
                "maintenance_stability_gate": 0.20,
                "minimum_effect_windows": 3,
                "context": "causal_active_goal_4x4",
                "post_bootstrap_generation_and_switch_cap": 25,
                "quota_rule": "at_most_B25_without_reactivation",
            },
        }
    )
    return protocol


def _runtime_manifest(expected_hashes, scenario_id: str):
    source_names = (
        "claim_runner",
        "validation_runner",
        "publication_policy",
        "frozen_cnn_generator",
        "online_ggo_adapter",
        "trafficflow_online_env",
        "task_generator",
        "period_on_sim",
        "checkpoint_file",
        "protocol",
    )
    sources = {
        name: {"path": f"/frozen/{name}", "sha256": expected_hashes[name]}
        for name in source_names
    }
    sources["map"] = {
        "path": f"/frozen/{scenario_id}.map",
        "sha256": expected_hashes[
            "narrow_map" if scenario_id.startswith("narrow_") else "regular_map"
        ],
    }
    return {
        "sources": sources,
        "environment": {
            "platform": "synthetic-linux",
            "python": "3.11",
            "numpy": "2.0",
            "torch": "2.6",
            "torch_cuda_available": True,
            "torch_cuda_version": "12.4",
            "torch_num_threads": 1,
            "torch_num_interop_threads": 1,
            "cpu_count": 8,
            "thread_environment": {
                "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "NUMEXPR_NUM_THREADS": "1",
                "VECLIB_MAXIMUM_THREADS": "1",
            },
        },
    }


def _write_attempt_ledger(path: Path, runs, agents: int):
    events = []
    for run in runs:
        identity = MODULE._attempt_identity(run, agents)
        attempt_id = MODULE._canonical_sha256(identity)
        events.append(
            {
                "schema": MODULE.ATTEMPT_LEDGER_SCHEMA,
                "event": "started",
                "attempt_id": attempt_id,
                "identity": identity,
                "runner_parent_process_id": run["execution_parent_process_id"],
                "time_ns": run["execution_process_start_ns"] - 1,
            }
        )
    for run in runs:
        identity = MODULE._attempt_identity(run, agents)
        attempt_id = MODULE._canonical_sha256(identity)
        events.append(
            {
                "schema": MODULE.ATTEMPT_LEDGER_SCHEMA,
                "event": "completed",
                "attempt_id": attempt_id,
                "identity": identity,
                "runner_parent_process_id": run["execution_parent_process_id"],
                "execution_process_id": run["execution_process_id"],
                "execution_host": run["execution_host"],
                "execution_process_start_ns": run["execution_process_start_ns"],
                "run_uuid": run["run_uuid"],
                "run_sha256": MODULE._canonical_sha256(run),
                "planner_timeouts": run["planner_timeouts"],
                "safety_passed": True,
                "invariants_passed": True,
                "time_ns": run["execution_process_start_ns"] + 1,
            }
        )
    path.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )
    return {
        "schema": MODULE.ATTEMPT_LEDGER_SCHEMA,
        "path": str(path),
        "sha256": _sha(path),
        "started_events": len(runs),
        "completed_events": len(runs),
    }


class SameCallConfirmationAnalyzerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        frozen = {}
        metadata = {
            "checkpoint_file": "a" * 64,
            "checkpoint_params": "b" * 64,
            "period_on_sim": "c" * 64,
            "narrow_map": MODULE.SCENARIOS["narrow_r020"]["map_sha256"],
            "regular_map": MODULE.SCENARIOS["regular_r020"]["map_sha256"],
        }
        for name in MODULE.REQUIRED_FROZEN_ARTIFACTS:
            if name in metadata:
                frozen[name] = {
                    "sha256": metadata[name],
                    "verification": "artifact_metadata",
                }
            elif name == "protocol":
                path = ROOT / "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-14.md"
                frozen[name] = {"path": str(path), "sha256": _sha(path)}
            elif name == "analyzer":
                frozen[name] = {"path": str(SCRIPT), "sha256": _sha(SCRIPT)}
            else:
                path = cls.directory / f"{name}.txt"
                path.write_text(name, encoding="utf-8")
                frozen[name] = {"path": str(path), "sha256": _sha(path)}

        preflight = {}
        for name in MODULE.REQUIRED_PREFLIGHT_KINDS:
            path = cls.directory / f"preflight-{name}.json"
            path.write_text(json.dumps({"passed": True}), encoding="utf-8")
            preflight[name] = {
                "path": str(path),
                "sha256": _sha(path),
                "passed": True,
            }
        cls.config = {
            "schema": "dai.same-call-confirmation/v1",
            "artifact_config_sha256_field": "development_matrix_config_sha256",
            "methods": list(MODULE.METHODS),
            "root_seeds": list(MODULE.ROOTS),
            "workloads": list(MODULE.WORKLOADS),
            "scenarios": [
                {
                    "id": scenario_id,
                    "map_sha256": values["map_sha256"],
                    "agents": values["agents"],
                }
                for scenario_id, values in MODULE.SCENARIOS.items()
            ],
            "protocol": {
                "warmup_time": 200,
                "scored_horizon": 2000,
                "decision_window": 20,
                "release_interval_per_agent": 110,
                "guard_suffix_tasks_per_agent": 4,
                "independent_inference_unit": "root_seed",
                "cells_per_root_seed_per_method": 12,
                "total_runs": 960,
                "bootstrap_samples": 10000,
                "bootstrap_seed": 20260715,
                "noninferiority_margin": 0.01,
            },
            "required_frozen_artifacts": sorted(MODULE.REQUIRED_FROZEN_ARTIFACTS),
            "frozen_artifacts": frozen,
            "preflight_evidence": preflight,
        }
        cls.config_path = cls.directory / "config.json"
        cls.config_path.write_text(
            json.dumps(cls.config, indent=2, sort_keys=True), encoding="utf-8"
        )
        cls.config_sha = _sha(cls.config_path)
        cls.expected_hashes = {
            name: record["sha256"] for name, record in frozen.items()
        }

        artifacts = []
        pid = 10_000
        for scenario_id, values in MODULE.SCENARIOS.items():
            runs = []
            for method in MODULE.METHODS:
                for root_seed in MODULE.ROOTS:
                    for workload in MODULE.WORKLOADS:
                        pid += 1
                        runs.append(
                            _make_run(
                                scenario_id=scenario_id,
                                method=method,
                                root_seed=root_seed,
                                workload=workload,
                                pid=pid,
                            )
                        )
            artifact = {
                    "schema": MODULE.SOURCE_SCHEMA,
                    "status": "complete",
                    "split": MODULE.SPLIT,
                    "evidence_class": MODULE.SPLIT,
                    "development_matrix_config_sha256": cls.config_sha,
                    "methods": list(MODULE.METHODS),
                    "seeds": list(MODULE.ROOTS),
                    "workloads": list(MODULE.WORKLOADS),
                    "map_id": f"map-{scenario_id}",
                    "map_path": f"/synthetic/map-{scenario_id}.map",
                    "map_sha256": values["map_sha256"],
                    "period_on_sim_sha256": "c" * 64,
                    "generator": {
                        "file_sha256": "a" * 64,
                        "params_sha256": "b" * 64,
                    },
                    "fresh_process_per_arm": True,
                    "runtime_manifest": _runtime_manifest(
                        cls.expected_hashes, scenario_id
                    ),
                    "protocol": _artifact_protocol(values["agents"]),
                    "runs": runs,
                }
            ledger_path = cls.directory / f"attempt-ledger-{scenario_id}.jsonl"
            artifact["attempt_ledger"] = _write_attempt_ledger(
                ledger_path, runs, values["agents"]
            )
            artifacts.append(artifact)
        cls.artifacts = artifacts

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def _audit_only(self, artifacts):
        artifacts = [dict(artifact) for artifact in artifacts]
        for index, artifact in enumerate(artifacts):
            scenario_id = next(
                scenario
                for scenario, values in MODULE.SCENARIOS.items()
                if values["map_sha256"] == artifact["map_sha256"]
                and values["agents"] == artifact["protocol"]["agents"]
            )
            ledger_path = self.directory / f"audit-ledger-{id(artifacts)}-{index}.jsonl"
            artifact["attempt_ledger"] = _write_attempt_ledger(
                ledger_path,
                artifact["runs"],
                MODULE.SCENARIOS[scenario_id]["agents"],
            )
        config, config_sha, path = MODULE.load_config(self.config_path)
        _, hashes = MODULE._verify_frozen_artifacts(config, path)
        return MODULE._normalize_and_audit(artifacts, config, config_sha, hashes)

    def test_frozen_schedule_vectors_are_complete(self):
        self.assertEqual(MODULE.exact_schedule(4), [25, 50, 75, 99])
        self.assertEqual(MODULE.exact_schedule(5), [20, 40, 60, 80, 99])
        self.assertEqual(
            MODULE.exact_schedule(25),
            [4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52,
             56, 60, 64, 68, 72, 76, 80, 84, 88, 92, 96, 99],
        )

    def test_complete_matrix_assigns_tier_a_and_emits_frozen_statistics(self):
        report = MODULE.analyze_artifacts(
            self.artifacts, config_path=self.config_path
        )
        self.assertTrue(report["audit"]["passed"])
        self.assertEqual(report["audit"]["totals"]["runs"], 960)
        self.assertEqual(
            report["audit"]["totals"]["unexposed_zero_route_completion_count"],
            960,
        )
        self.assertEqual(report["design"]["bootstrap_samples"], 10000)
        self.assertEqual(report["design"]["bootstrap_seed"], 20260715)
        self.assertEqual(report["multiplicity"]["family_size"], 6)
        self.assertTrue(report["noninferiority_vs_exact_even_B25"]["passed"])
        self.assertEqual(report["outcome_tier"]["tier"], "A")
        self.assertEqual(
            len(
                report["superiority_comparisons"]["exact_even_G5"]
                ["leave_one_root_out_means"]
            ),
            10,
        )
        self.assertEqual(
            set(report["superiority_comparisons"]["exact_even_G5"]["map_effects"]),
            {"narrow", "regular"},
        )
        calls = report["method_summaries"]["context_memory_B25"][
            "total_generator_calls"
        ]
        self.assertEqual(calls["mean"], 5.0)
        self.assertEqual(calls["fraction_at_most_5"], 1.0)
        self.assertIn("context_memory_B25", report["pareto"]["frontier_methods"])

    def test_config_hash_mismatch_is_rejected(self):
        artifacts = list(self.artifacts)
        artifacts[0] = dict(artifacts[0])
        artifacts[0]["development_matrix_config_sha256"] = "0" * 64
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "config hash"):
            MODULE.analyze_artifacts(artifacts, config_path=self.config_path)

    def test_source_hash_mismatch_is_rejected(self):
        config = json.loads(json.dumps(self.config))
        config["frozen_artifacts"]["claim_runner"]["sha256"] = "0" * 64
        path = self.directory / "bad-source-config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "hash mismatch"):
            MODULE.analyze_artifacts(self.artifacts, config_path=path)

    def test_pairing_drift_fails_audit(self):
        artifacts, run = _clone_run(self.artifacts, 0, 0)
        run["release_projection_fingerprint"] = "0" * 64
        _, failures, _ = self._audit_only(artifacts)
        self.assertTrue(
            any(
                item["category"] == "pairing"
                and item["check"] == "paired_release_projection_fingerprint"
                for item in failures
            )
        )

    def test_random_schedule_drift_fails_audit(self):
        artifact_index = 0
        run_index = next(
            index
            for index, run in enumerate(self.artifacts[artifact_index]["runs"])
            if run["method"] == "random_G5"
        )
        artifacts, run = _clone_run(self.artifacts, artifact_index, run_index)
        run["precommitted_post_bootstrap_schedule"] = [1, 2, 3, 4, 5]
        _, failures, _ = self._audit_only(artifacts)
        self.assertTrue(any(item["check"] == "random_schedule_precommitted" for item in failures))

    def test_no_reactivation_recall_fails_audit(self):
        run_index = next(
            index
            for index, run in enumerate(self.artifacts[0]["runs"])
            if run["method"] == "context_no_reactivation_B25"
        )
        artifacts, run = _clone_run(self.artifacts, 0, run_index)
        run["publication_timeline"] = list(run["publication_timeline"])
        row = dict(run["publication_timeline"][20])
        row["executed_operation"] = "reactivate"
        row["charged_to_generator_budget"] = False
        run["publication_timeline"][20] = row
        _, failures, _ = self._audit_only(artifacts)
        self.assertTrue(any(item["check"] == "timeline_has_no_reactivate" for item in failures))

    def test_unknown_route_attribution_reason_fails_audit(self):
        artifacts, run = _clone_run(self.artifacts, 0, 0)
        run["route_build_reason_counts"] = {"unknown": 1}
        run["cohort_attribution_audit"] = dict(run["cohort_attribution_audit"])
        run["cohort_attribution_audit"]["route_build_reason_counts"] = {"unknown": 1}
        _, failures, _ = self._audit_only(artifacts)
        self.assertTrue(
            any(item["check"] == "recognized_route_build_reasons" for item in failures)
        )

    def test_duplicate_execution_process_fails_audit(self):
        artifacts, run = _clone_run(self.artifacts, 0, 1)
        run["execution_process_id"] = artifacts[0]["runs"][0]["execution_process_id"]
        _, failures, _ = self._audit_only(artifacts)
        self.assertTrue(any(item["check"] == "one_unique_os_process_per_arm" for item in failures))

    def test_preflight_failure_is_rejected_before_inference(self):
        config = json.loads(json.dumps(self.config))
        config["preflight_evidence"]["rng_isolation"]["passed"] = False
        path = self.directory / "bad-preflight-config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "not declared passed"):
            MODULE.analyze_artifacts(self.artifacts, config_path=path)

    def test_completed_status_cannot_override_explicit_preflight_failure(self):
        report_path = self.directory / "false-complete-preflight.json"
        report_path.write_text(
            json.dumps(
                {
                    "passed": False,
                    "status": "complete",
                    "audit": {"passed": False},
                }
            ),
            encoding="utf-8",
        )
        config = json.loads(json.dumps(self.config))
        config["preflight_evidence"]["rng_isolation"] = {
            "path": str(report_path),
            "sha256": _sha(report_path),
            "passed": True,
        }
        path = self.directory / "false-complete-preflight-config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "does not report PASS"):
            MODULE.analyze_artifacts(self.artifacts, config_path=path)

    def test_declared_task_count_is_recomputed_from_all_windows(self):
        artifacts, run = _clone_run(self.artifacts, 0, 0)
        run["num_task_finished"] += 100_000
        run["throughput_per_timestep"] = run["num_task_finished"] / 2000.0
        _, failures, _ = self._audit_only(artifacts)
        self.assertTrue(
            any(
                item["check"]
                == "window_reward_and_completion_trajectory_recomputed"
                for item in failures
            )
        )

    def test_same_aggregate_but_relocated_generation_fails_exact_timeline(self):
        run_index = next(
            index
            for index, run in enumerate(self.artifacts[0]["runs"])
            if run["method"] == "exact_even_G5"
        )
        artifacts, run = _clone_run(self.artifacts, 0, run_index)
        run["publication_timeline"] = list(run["publication_timeline"])
        at_20 = dict(run["publication_timeline"][20])
        at_21 = dict(run["publication_timeline"][21])
        at_20.update(
            {
                "executed_operation": "hold",
                "charged_to_post_bootstrap_generation_cap": False,
                "charged_to_generator_budget": False,
            }
        )
        at_21.update(
            {
                "executed_operation": "generate",
                "charged_to_post_bootstrap_generation_cap": True,
                "charged_to_generator_budget": True,
            }
        )
        run["publication_timeline"][20] = at_20
        run["publication_timeline"][21] = at_21
        _, failures, _ = self._audit_only(artifacts)
        self.assertTrue(any(item["check"] == "g5_schedule" for item in failures))
        self.assertTrue(
            any(
                item["check"] == "post_row_operation_charge_bijection"
                for item in failures
            )
        )

    def test_bootstrap_timeline_row_is_not_self_attested(self):
        artifacts, run = _clone_run(self.artifacts, 0, 0)
        run["publication_timeline"] = list(run["publication_timeline"])
        bootstrap = dict(run["publication_timeline"][0])
        bootstrap.update(
            {
                "requested": False,
                "accepted": False,
                "requested_operation": "hold",
                "executed_operation": "hold",
            }
        )
        run["publication_timeline"][0] = bootstrap
        _, failures, _ = self._audit_only(artifacts)
        self.assertTrue(
            any(item["check"] == "bootstrap_is_mandatory_generation" for item in failures)
        )

    def test_artifact_protocol_is_bound_to_frozen_horizon(self):
        artifacts = list(self.artifacts)
        artifact = dict(artifacts[0])
        artifact["protocol"] = dict(artifact["protocol"])
        artifact["protocol"]["scored_horizon"] = 123
        artifacts[0] = artifact
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "scored_horizon"):
            self._audit_only(artifacts)

    def test_missing_pairing_payload_cannot_compare_as_all_null(self):
        artifacts = list(self.artifacts)
        artifact = dict(artifacts[0])
        artifact["runs"] = list(artifact["runs"])
        target_root = MODULE.ROOTS[0]
        target_workload = MODULE.WORKLOADS[0]
        fields = (
            "manifest_id",
            "task_tape_identity",
            "reset_causal_fingerprint",
            "release_projection_fingerprint",
            "distribution_update_fingerprint",
            "workload_arrival",
        )
        for index, original in enumerate(artifact["runs"]):
            if original["root_seed"] == target_root and original["workload"] == target_workload:
                run = dict(original)
                for field in fields:
                    run.pop(field)
                artifact["runs"][index] = run
        artifacts[0] = artifact
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "manifest_id"):
            self._audit_only(artifacts)

    def test_behavior_source_cannot_use_metadata_only_fake_hash(self):
        config = json.loads(json.dumps(self.config))
        digest = config["frozen_artifacts"]["claim_runner"]["sha256"]
        config["frozen_artifacts"]["claim_runner"] = {
            "sha256": digest,
            "verification": "artifact_metadata",
        }
        path = self.directory / "metadata-only-behavior-config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "local path"):
            MODULE.analyze_artifacts(self.artifacts, config_path=path)

    def test_attempt_ledger_run_hash_must_match_retained_run(self):
        artifacts = [dict(artifact) for artifact in self.artifacts]
        artifact = artifacts[0]
        events = [
            json.loads(line)
            for line in Path(artifact["attempt_ledger"]["path"])
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        completed = next(event for event in events if event["event"] == "completed")
        completed["run_sha256"] = "0" * 64
        path = self.directory / "tampered-attempt-ledger.jsonl"
        path.write_text(
            "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
            encoding="utf-8",
        )
        artifact["attempt_ledger"] = {
            **artifact["attempt_ledger"],
            "path": str(path),
            "sha256": _sha(path),
        }
        config, config_sha, config_path = MODULE.load_config(self.config_path)
        _, hashes = MODULE._verify_frozen_artifacts(config, config_path)
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "run hash"):
            MODULE._normalize_and_audit(artifacts, config, config_sha, hashes)

    def test_guidance_hash_requires_lowercase_sha256(self):
        artifacts, run = _clone_run(self.artifacts, 0, 0)
        run["windows"] = list(run["windows"])
        window = dict(run["windows"][0])
        window["guidance_sha256"] = "G" * 64
        run["windows"][0] = window
        _, failures, _ = self._audit_only(artifacts)
        self.assertTrue(any(item["check"] == "guidance_hashes_complete" for item in failures))

    def test_planner_timeouts_are_retained_and_cross_checked(self):
        artifacts, run = _clone_run(self.artifacts, 0, 0)
        run["planner_timeouts"] = 1
        _, failures, _ = self._audit_only(artifacts)
        self.assertTrue(
            any(
                item["check"] == "planner_timeouts_retained_and_consistent"
                for item in failures
            )
        )

    def test_runtime_thread_contract_rejects_multithread_drift(self):
        artifacts = list(self.artifacts)
        artifact = dict(artifacts[0])
        runtime = dict(artifact["runtime_manifest"])
        environment = dict(runtime["environment"])
        thread_environment = dict(environment["thread_environment"])
        thread_environment["OMP_NUM_THREADS"] = "2"
        environment["thread_environment"] = thread_environment
        runtime["environment"] = environment
        artifact["runtime_manifest"] = runtime
        artifacts[0] = artifact
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "OMP_NUM_THREADS"):
            self._audit_only(artifacts)

    def test_real_launcher_context_recall_threshold_fixture_is_005(self):
        self.assertEqual(
            self.artifacts[0]["protocol"][MODULE.FOCAL]["recall_threshold"],
            0.05,
        )
        self._audit_only(self.artifacts)


if __name__ == "__main__":
    unittest.main()
