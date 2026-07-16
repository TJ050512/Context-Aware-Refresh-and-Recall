import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import uuid


WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT = WORKSPACE / "scripts" / "audit_same_call_preflight_v1.py"
SPEC = importlib.util.spec_from_file_location("audit_same_call_preflight_v1", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(run, agents):
    return {
        "split": run["split"],
        "map_id": run["map_id"],
        "agents": agents,
        "seed": run["seed"],
        "workload": run["workload"],
        "method": run["method"],
    }


def _schedule(method):
    if method in MODULE.EXACT_SCHEDULES:
        return list(MODULE.EXACT_SCHEDULES[method])
    if method == "random_G5":
        return [7, 27, 47, 67, 87]
    if method == "js_cap_G5":
        return [30, 70]
    if method in {"context_no_reactivation_B25", "context_memory_B25"}:
        return [25, 65]
    raise AssertionError(method)


def _run(map_id, workload, method, pid, *, tape_hash="tape", suffix=False):
    schedule = _schedule(method)
    version = 1
    timeline = []
    windows = []
    timeline.append({
        "decision_index": 0,
        "scored_timestep": 0,
        "absolute_timestep": 200,
        "requested": True,
        "accepted": True,
        "reason": "mandatory_bootstrap",
        "requested_operation": "bootstrap_generate",
        "executed_operation": "bootstrap_generate",
        "guidance_version_before_decision": 0,
        "guidance_version_installed_for_window": 1,
        "active_generation_id_after": 1,
    })
    completed = 0
    for index in range(100):
        operation = "generate" if index in schedule else "hold"
        if index > 0:
            before = version
            if operation == "generate":
                version += 1
            timeline.append({
                "decision_index": index,
                "scored_timestep": index * 20,
                "absolute_timestep": 200 + index * 20,
                "requested": operation == "generate",
                "accepted": operation == "generate",
                "reason": "synthetic",
                "policy": {
                    "epoch": index - 1,
                    "accepted": operation == "generate",
                },
                "requested_operation": operation,
                "executed_operation": operation,
                "guidance_version_before_decision": before,
                "guidance_version_installed_for_window": version,
                "active_generation_id_after": version,
            })
        completed += 2
        window_operation = "hold" if index == 0 else operation
        windows.append({
            "decision_index": index,
            "window_start_timestep": 200 + index * 20,
            "window_end_timestep": 220 + index * 20,
            "reward": 2.0,
            "refreshed_post_bootstrap": index > 0 and operation == "generate",
            "guidance_switched_post_bootstrap": index > 0 and operation == "generate",
            "guidance_operation": window_operation,
            "generation_id": version,
            "installation_version": version,
            "guidance_version": version,
            "guidance_sha256": f"raw-{version}",
            "applied_guidance_sha256": f"applied-{version}",
            "map_weights_revision": version,
            "num_task_finished": completed,
            "planner_seconds": 0.01 + pid / 1e9,
            "generator_seconds": 0.02 if operation == "generate" else 0.0,
            "simulator_seconds": 0.03,
            "released_count": 1,
            "assigned_prefix_total": index + 1,
            "completed_prefix_total": index,
            "features": {"causal_block_score": index / 100},
        })
    generations = len(schedule)
    exact = method in MODULE.EXACT_SCHEDULES or method == "random_G5"
    budget = {
        "mandatory_bootstrap_calls": 1,
        "post_bootstrap_publication_count": generations,
        "post_bootstrap_generation_count": generations,
        "post_bootstrap_reactivation_count": 0,
        "effective_guidance_switch_count": generations,
        "total_generator_calls": 1 + generations,
        "cap_satisfied": True,
        "switch_cap_satisfied": True,
        "generation_cap_satisfied": True,
        "total_generator_call_cap_satisfied": True,
        "generator_call_conservation_satisfied": True,
        "switch_operation_partition_satisfied": True,
        "generation_cap_binding_audit_satisfied": True,
        "eventreserve_audit_conservation_satisfied": True,
        "budget_violation_attempts": 0,
        "exact_quota_required": exact,
        "exact_quota_satisfied": exact,
    }
    identity = {
        "mode": "absolute_release_queue_per_agent",
        "schema_version": "dai.kiva-absolute-release-tape/v1",
        "manifest_sha256": tape_hash,
        "content_fnv1a64": hashlib.sha256(tape_hash.encode()).hexdigest()[:16],
        "start_locations": [1, 2],
        "per_agent_lengths": [24, 24],
        "total_tasks": 48,
    }
    return {
        "method": method,
        "execution_process_id": pid,
        "execution_parent_process_id": 1,
        "execution_host": "test-host",
        "execution_process_start_ns": 1_000_000 + pid,
        "run_uuid": str(uuid.UUID(int=(pid << 64) + 4, version=4)),
        "seed": 17,
        "root_seed": 17,
        "split": "development",
        "evidence_class": "development",
        "map_id": map_id,
        "map_path": f"/maps/{map_id}.map",
        "workload": workload,
        "manifest_id": f"{map_id}:{workload}:{tape_hash}",
        "num_task_finished": completed,
        "throughput_per_timestep": completed / 2000,
        "scored_horizon": 2000,
        "decision_window": 20,
        "window_count": 100,
        "mandatory_bootstrap_calls": 1,
        "post_bootstrap_publication_count": generations,
        "post_bootstrap_generation_count": generations,
        "post_bootstrap_reactivation_count": 0,
        "effective_guidance_switch_count": generations,
        "publication_budget": generations if exact else 25,
        "budget_violation_count": 0,
        "budget": budget,
        "safety": {
            "passed": True,
            "collision_count": 0,
            "edge_swap_count": 0,
            "endpoint_mismatch_count": 0,
            "invalid_move_count": 0,
            "planner_timeout_count": 0,
            "route_trace_invalid_count": 0,
        },
        "collisions": 0,
        "edge_swaps": 0,
        "invalid_moves": 0,
        "planner_timeouts": 0,
        "task_tape_identity": identity,
        "final_task_tape_prefixes": {
            "released_prefix_lengths": [20, 20],
            "assigned_prefix_lengths": [19, 19],
            "completed_prefix_lengths": [18, 18],
            "all_released": False,
            "all_completed": False,
        },
        "reset_causal_fingerprint": f"reset-{map_id}-{workload}-{tape_hash}",
        "release_projection_fingerprint": f"release-{map_id}-{workload}-{tape_hash}",
        "distribution_update_fingerprint": f"distribution-{map_id}-{workload}",
        "publication_timeline": timeline,
        "precommitted_post_bootstrap_schedule": schedule if exact else None,
        "guidance_catalog": [],
        "windows": windows,
        "workload_arrival": {"workload": workload, "root_seed": 17},
        "generator_calls": 1 + generations,
        "generator_seconds": 1.0 + pid / 1e9,
        "simulator_seconds": 2.0 + pid / 1e9,
        "elapsed_seconds": 3.0 + pid / 1e9,
        "timing_evidence_valid": False,
        "invariants": {
            "passed": True,
            "online_workload_rng_draws": 0,
            "release_projection_count": 48,
            "tape_not_exhausted": True,
            "reward_sum_matches_completed": True,
            "unexposed_completions_excluded_from_cohorts": True,
        },
    }


def _write_artifact(root, label, map_id, agents, methods, workloads, pid_start, *, suffix_variant=0, cutoff=2200):
    scenario = MODULE.EXPECTED_SCENARIOS[(map_id, agents)]
    tape_hash = f"tape-{map_id}-{agents}"
    if suffix_variant:
        tape_hash += f"-variant-{suffix_variant}"
    runs = []
    pid = pid_start
    for workload in workloads:
        for method in methods:
            runs.append(_run(map_id, workload, method, pid, tape_hash=tape_hash))
            pid += 1
    path = root / f"{label}.json"
    ledger = root / f"{label}.attempts.jsonl"
    events = []
    for run in runs:
        identity = _identity(run, agents)
        attempt_id = MODULE._strict_sha(identity)
        events.append({
            "schema": MODULE.ATTEMPT_SCHEMA,
            "event": "started",
            "attempt_id": attempt_id,
            "identity": identity,
            "runner_parent_process_id": 1,
            "time_ns": 1,
        })
    for run in runs:
        identity = _identity(run, agents)
        events.append({
            "schema": MODULE.ATTEMPT_SCHEMA,
            "event": "completed",
            "attempt_id": MODULE._strict_sha(identity),
            "identity": identity,
            "runner_parent_process_id": 1,
            "execution_process_id": run["execution_process_id"],
            "execution_host": run["execution_host"],
            "execution_process_start_ns": run["execution_process_start_ns"],
            "run_uuid": run["run_uuid"],
            "run_sha256": MODULE._strict_sha(run),
            "planner_timeouts": 0,
            "safety_passed": True,
            "invariants_passed": True,
            "time_ns": 2,
        })
    ledger.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))
    artifact = {
        "schema": MODULE.ARTIFACT_SCHEMA,
        "status": "complete",
        "split": "development",
        "evidence_class": "development",
        "fresh_process_per_arm": True,
        "attempt_ledger": {
            "schema": MODULE.ATTEMPT_SCHEMA,
            "path": str(ledger),
            "sha256": _sha_file(ledger),
            "started_events": len(runs),
            "completed_events": len(runs),
        },
        "seeds": [17],
        "methods": list(methods),
        "workloads": list(workloads),
        "map_id": map_id,
        "map_path": f"/maps/{map_id}.map",
        "map_sha256": scenario[1],
        "period_on_sim_sha256": MODULE.SIMULATOR_SHA256,
        "runtime_manifest": {"environment": {"host": "test-host"}},
        "protocol": {
            "agents": agents,
            "warmup_time": 200,
            "scored_horizon": 2000,
            "decision_window": 20,
            "num_scored_windows": 100,
            "eligible_post_bootstrap_decisions": 99,
            "b25_budget": 25,
            "release_interval_per_agent": 110,
            "guard_suffix_tasks_per_agent": 4,
            "sigma": 0.75,
            "fresh_os_process_per_arm": True,
            "exclusive_timing_declared": False,
            "timing_evidence_valid": False,
            "future_suffix_variant": suffix_variant,
            "future_suffix_cutoff_absolute": cutoff,
        },
        "generator": {
            "file_sha256": MODULE.CHECKPOINT_SHA256,
            "params_sha256": MODULE.CHECKPOINT_PARAMS_SHA256,
        },
        "runs": runs,
    }
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    return path, artifact


def _write_event_archive(root, smoke_artifacts):
    archive_path = root / "event.tgz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for label, artifact in smoke_artifacts.items():
            agents = artifact["protocol"]["agents"]
            runs = [
                copy.deepcopy(run)
                for run in artifact["runs"]
                if run["method"] in MODULE.COMMON_ARMS
            ]
            old = {
                "schema": MODULE.ARTIFACT_SCHEMA,
                "status": "complete",
                "protocol": {"agents": agents},
                "map_id": artifact["map_id"],
                "runs": runs,
            }
            payload = json.dumps(old, sort_keys=True).encode()
            info = tarfile.TarInfo(f"results/development_eventreserve/matrix_v1_{label}.json")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return archive_path


class SameCallPreflightFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.smoke_paths = []
        self.smoke = {}
        pid = 100
        for (map_id, agents), (label, _) in MODULE.EXPECTED_SCENARIOS.items():
            path, artifact = _write_artifact(
                self.root, label, map_id, agents, MODULE.METHODS, MODULE.WORKLOADS, pid
            )
            pid += 24
            self.smoke_paths.append(path)
            self.smoke[label] = artifact
        self.archive = _write_event_archive(self.root, self.smoke)
        self.repeat_a, _ = _write_artifact(
            self.root, "repeat_a", "warehouse_small_narrow_kiva", 218,
            MODULE.REPLAY_ARMS, ("stationary",), 1000,
        )
        self.repeat_b, _ = _write_artifact(
            self.root, "repeat_b", "warehouse_small_narrow_kiva", 218,
            MODULE.REPLAY_ARMS, ("stationary",), 1100,
        )
        self.suffix_base, _ = _write_artifact(
            self.root, "future_suffix_base", "warehouse_small_narrow_kiva", 218,
            MODULE.REPLAY_ARMS, ("stationary",), 1200, cutoff=1400,
        )
        self.suffix_variant, _ = _write_artifact(
            self.root, "future_suffix_variant", "warehouse_small_narrow_kiva", 218,
            MODULE.REPLAY_ARMS, ("stationary",), 1300, suffix_variant=1, cutoff=1400,
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_full(self):
        return MODULE.run_audit(
            smoke_artifacts=self.smoke_paths,
            eventreserve_evidence=self.archive,
            repeat_a=self.repeat_a,
            repeat_b=self.repeat_b,
            future_suffix_base=self.suffix_base,
            future_suffix_variant=self.suffix_variant,
            expected_evidence_sha256=None,
        )

    def rewrite_ledger(self, artifact_path, artifact):
        ledger = Path(artifact["attempt_ledger"]["path"])
        runs = {
            MODULE._strict_sha(_identity(run, artifact["protocol"]["agents"])): run
            for run in artifact["runs"]
        }
        events = [json.loads(line) for line in ledger.read_text().splitlines()]
        for event in events:
            if event["event"] == "completed":
                event["run_sha256"] = MODULE._strict_sha(runs[event["attempt_id"]])
        ledger.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        )
        artifact["attempt_ledger"]["sha256"] = _sha_file(ledger)
        artifact_path.write_text(json.dumps(artifact, sort_keys=True))


class SameCallPreflightPassTests(SameCallPreflightFixture):
    def test_complete_preflight_passes_without_effect_inference(self):
        result = self.run_full()
        self.assertTrue(result["passed"])
        self.assertEqual(result["audit"]["smoke_matrix"]["runs"], 96)
        self.assertEqual(
            result["audit"]["smoke_matrix"]["archived_common_arm_comparisons"],
            36,
        )
        self.assertFalse(result["audit"]["effect_inference_performed"])
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn("mean_throughput", rendered)
        self.assertNotIn("relative_effect", rendered)

    def test_directory_resolution_selects_only_four_artifacts(self):
        # The replay artifacts live in the same fixture directory, so use four
        # explicit paths; a clean directory case is checked independently.
        clean = self.root / "smoke_only"
        clean.mkdir()
        for path in self.smoke_paths:
            (clean / path.name).write_bytes(path.read_bytes())
        self.assertEqual(len(MODULE.resolve_smoke_artifacts([clean])), 4)


class SameCallPreflightFailureTests(SameCallPreflightFixture):
    def test_incomplete_attempt_ledger_is_rejected(self):
        path = self.smoke_paths[0]
        artifact = json.loads(path.read_text())
        ledger = Path(artifact["attempt_ledger"]["path"])
        lines = ledger.read_text().splitlines()
        ledger.write_text("\n".join(lines[:-1]) + "\n")
        artifact["attempt_ledger"]["sha256"] = _sha_file(ledger)
        path.write_text(json.dumps(artifact))
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "event count"):
            self.run_full()

    def test_cross_method_pairing_mismatch_is_rejected(self):
        path = self.smoke_paths[0]
        artifact = json.loads(path.read_text())
        artifact["runs"][0]["reset_causal_fingerprint"] = "wrong"
        self.rewrite_ledger(path, artifact)
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "paired reset"):
            self.run_full()

    def test_all_missing_pairing_fields_cannot_pass_by_equal_nulls(self):
        path = self.smoke_paths[0]
        artifact = json.loads(path.read_text())
        for run in artifact["runs"]:
            for field in (
                "manifest_id",
                "task_tape_identity",
                "reset_causal_fingerprint",
                "release_projection_fingerprint",
                "distribution_update_fingerprint",
            ):
                run[field] = None
        self.rewrite_ledger(path, artifact)
        with self.assertRaisesRegex(
            MODULE.PreflightAuditError,
            "manifest_id must be a non-empty string",
        ):
            self.run_full()

    def test_random_schedule_must_match_across_all_cells(self):
        path = self.smoke_paths[0]
        artifact = json.loads(path.read_text())
        run = next(
            run for run in artifact["runs"]
            if run["method"] == "random_G5" and run["workload"] == "stationary"
        )
        # Retain a valid five-call exact schedule but make this cell different.
        for entry in run["publication_timeline"]:
            if entry["decision_index"] == 7:
                entry["accepted"] = False
                entry["executed_operation"] = "hold"
            if entry["decision_index"] == 8:
                entry["accepted"] = True
                entry["executed_operation"] = "generate"
        for window in run["windows"]:
            if window["decision_index"] == 7:
                window["guidance_operation"] = "hold"
                window["guidance_switched_post_bootstrap"] = False
            if window["decision_index"] == 8:
                window["guidance_operation"] = "generate"
                window["guidance_switched_post_bootstrap"] = True
        run["precommitted_post_bootstrap_schedule"] = [8, 27, 47, 67, 87]
        self.rewrite_ledger(path, artifact)
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "random_G5 schedule"):
            self.run_full()

    def test_archived_semantic_drift_is_rejected(self):
        # Rebuild an archive with one altered completion trajectory.
        altered = copy.deepcopy(self.smoke)
        first = next(iter(altered.values()))
        run = next(run for run in first["runs"] if run["method"] == "bootstrap_only")
        run["windows"][10]["reward"] += 1
        archive = _write_event_archive(self.root / "altered", altered) if False else None
        sub = self.root / "altered_archive"
        sub.mkdir()
        archive = _write_event_archive(sub, altered)
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "archived deterministic replay"):
            MODULE.audit_smoke(self.smoke_paths, archive, expected_evidence_sha256=None)

    def test_repeat_drift_is_rejected(self):
        artifact = json.loads(self.repeat_b.read_text())
        artifact["runs"][0]["windows"][5]["reward"] += 1
        self.rewrite_ledger(self.repeat_b, artifact)
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "repeatability"):
            MODULE.audit_repeats(self.repeat_a, self.repeat_b)

    def test_future_suffix_pre_cutoff_drift_is_rejected(self):
        artifact = json.loads(self.suffix_variant.read_text())
        artifact["runs"][0]["windows"][5]["guidance_sha256"] = "changed-too-early"
        self.rewrite_ledger(self.suffix_variant, artifact)
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "pre-cutoff windows"):
            MODULE.audit_future_suffix(self.suffix_base, self.suffix_variant)

    def test_future_suffix_window_ending_at_cutoff_is_included(self):
        artifact = json.loads(self.suffix_variant.read_text())
        boundary = artifact["runs"][0]["windows"][59]
        self.assertEqual(boundary["window_end_timestep"], 1400)
        boundary["reward"] += 1
        self.rewrite_ledger(self.suffix_variant, artifact)
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "pre-cutoff windows"):
            MODULE.audit_future_suffix(self.suffix_base, self.suffix_variant)

    def test_future_suffix_requires_a_different_complete_tape(self):
        variant = json.loads(self.suffix_variant.read_text())
        base = json.loads(self.suffix_base.read_text())
        for run in variant["runs"]:
            source = next(item for item in base["runs"] if item["method"] == run["method"])
            run["task_tape_identity"] = copy.deepcopy(source["task_tape_identity"])
        self.rewrite_ledger(self.suffix_variant, variant)
        with self.assertRaisesRegex(MODULE.PreflightAuditError, "complete tape"):
            MODULE.audit_future_suffix(self.suffix_base, self.suffix_variant)


if __name__ == "__main__":
    unittest.main()
