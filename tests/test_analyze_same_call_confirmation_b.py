import copy
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "analyze_same_call_confirmation_b.py"
V1_PATH = ROOT / "scripts" / "analyze_same_call_confirmation_v1.py"
A2_CONFIG = ROOT / "configs" / "same_call_confirmation_a2.json"


def _load():
    spec = importlib.util.spec_from_file_location(
        "analyze_same_call_confirmation_b_test", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = _load()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _b_config():
    config = json.loads(A2_CONFIG.read_text(encoding="utf-8"))
    config.update(
        {
            "schema": MODULE.B_CONFIG_SCHEMA,
            "status": "content_hashed_internal_pre_specification_frozen_before_b_matrix",
            "execution_host": "synthetic-b-host",
            "public_preregistration": False,
            "standalone_replication": True,
            "primary_analysis_pools_with_a1_or_a2": False,
            "root_seeds": list(MODULE.B_ROOTS),
            "root_derivation": {
                "source_sha256": MODULE.B_DERIVATION_SOURCE_SHA256,
                "domain": MODULE.B_DOMAIN,
                "formula": MODULE.B_DERIVATION_FORMULA,
                "index_start": 0,
                "index_end": 39,
                "count": 40,
            },
            "process_identity_gate": {
                "bare_pid_uniqueness_is_gate": False,
                "hard_identity": [
                    "execution_host",
                    "execution_process_id",
                    "execution_process_start_ns",
                ],
                "unique_process_instances_required": MODULE.B_TOTAL_RUNS,
                "unique_run_uuids_required": MODULE.B_TOTAL_RUNS,
            },
            "execution": {
                "jobs_per_scenario": 30,
                "scenario_processes": 4,
                "thread_environment": {name: "1" for name in MODULE.THREAD_ENV},
                "runs_per_scenario": MODULE.B_RUNS_PER_SCENARIO,
                "attempt_ledger_events_per_scenario": (
                    MODULE.B_LEDGER_EVENTS_PER_SCENARIO
                ),
                "total_runs": MODULE.B_TOTAL_RUNS,
            },
            "target_environment": {
                "execution_host": "synthetic-b-host",
                "path": "reports/attestation-b.json",
                "sha256": "a" * 64,
                "host_instance_fingerprint_sha256": "b" * 64,
                "compatibility_projection_sha256": "c" * 64,
            },
            "analysis_contract": {
                "execute_after_complete_integrity_audit_only": True,
                "execute_content_hashed_analyzer_exactly_once": True,
                "whole_root_bootstrap_samples": 10000,
                "whole_root_bootstrap_seed": 20260715,
                "singleton_noninferiority_separate_from_holm_family": True,
                "report_regardless_of_direction": True,
            },
            "provenance": {
                "b_effect_estimates_computed_before_config": 0,
                "b_fresh_root_runs_observed_at_freeze": 0,
                "b_method_rankings_inspected_before_config": 0,
                "effect_inference_performed_before_config": False,
                "prior_a2_outcomes_known": True,
                "standalone_primary_analysis": True,
                "pool_with_a2": False,
                "implementation_freeze_path": "configs/freeze-b.json",
                "implementation_freeze_sha256": "f" * 64,
            },
        }
    )
    config["protocol"].update(
        {
            "total_runs": MODULE.B_TOTAL_RUNS,
            "runs_per_scenario": MODULE.B_RUNS_PER_SCENARIO,
            "attempt_ledger_events_per_scenario": (
                MODULE.B_LEDGER_EVENTS_PER_SCENARIO
            ),
            "attempt_starts_per_scenario": MODULE.B_RUNS_PER_SCENARIO,
            "attempt_completions_per_scenario": MODULE.B_RUNS_PER_SCENARIO,
            "split": MODULE.V1.SPLIT,
            "fresh_process_per_arm": True,
            "noninferiority_point_estimate_gate": -0.005,
            "noninferiority_comparator": "exact_even_B25",
            "noninferiority_method": "context_memory_B25",
            "noninferiority_alpha": 0.05,
            "superiority_holm_family_size": 6,
        }
    )
    additions = {
        "analyzer_b": {
            "path": "scripts/analyze_same_call_confirmation_b.py",
            "sha256": _sha(SCRIPT),
        },
        "builder_b": {"path": "scripts/builder-b.py", "sha256": "8" * 64},
        "capture_environment_b": {
            "path": "scripts/capture-b.py",
            "sha256": "7" * 64,
        },
        "launcher_b": {"path": "scripts/launcher-b.sh", "sha256": "d" * 64},
        "protocol_b": {
            "path": "EXPERIMENT_PROTOCOL_SAME_CALL_2026-07-15_B.md",
            "sha256": MODULE.B_PROTOCOL_SHA256,
        },
        "predecessor_a2_config": {
            "path": "configs/same_call_confirmation_a2.json",
            "sha256": "9" * 64,
        },
        "runner_b": {"path": "scripts/runner-b.py", "sha256": "e" * 64},
    }
    config["frozen_artifacts"].update(additions)
    config["required_frozen_artifacts"] = sorted(
        set(config["required_frozen_artifacts"]) | set(additions)
    )
    config["preflight_evidence"] = {
        label: copy.deepcopy(config["preflight_evidence"][label])
        for label in MODULE.INHERITED_PREFLIGHT_KINDS
    }
    config["preflight_evidence"][MODULE.B_SMOKE_PREFLIGHT_KIND] = copy.deepcopy(
        config["preflight_evidence"]["engineering_smoke"]
    )
    config["preflight_evidence"][MODULE.B_ENVIRONMENT_PREFLIGHT_KIND] = {
        "path": config["target_environment"]["path"],
        "sha256": config["target_environment"]["sha256"],
        "passed": True,
        "b_fresh_root_runs_observed": 0,
    }
    config["required_preflight_evidence"] = sorted(config["preflight_evidence"])
    config["provenance"]["predecessor_a2_config_sha256"] = "9" * 64
    return config


class SameCallConfirmationBAnalyzerTests(unittest.TestCase):
    def test_frozen_dependencies_protocol_and_roots(self):
        self.assertEqual(_sha(V1_PATH), MODULE.V1_SHA256)
        self.assertEqual(_sha(MODULE.B_PROTOCOL_PATH), MODULE.B_PROTOCOL_SHA256)
        self.assertEqual(MODULE._derive_b_roots(), MODULE.B_ROOTS)
        self.assertEqual(len(MODULE.B_ROOTS), 40)
        self.assertEqual(len(set(MODULE.B_ROOTS)), 40)

    def test_all_b_cardinalities_and_names_are_bound(self):
        self.assertEqual(MODULE.V1.ROOTS, MODULE.B_ROOTS)
        self.assertEqual(MODULE.V1.TOTAL_RUNS, 3840)
        self.assertEqual(MODULE.V1.RUNS_PER_SCENARIO, 960)
        self.assertEqual(MODULE.B_LEDGER_EVENTS_PER_SCENARIO, 1920)
        self.assertEqual(MODULE.B_PAIRED_CELLS_PER_METHOD, 480)
        self.assertEqual(MODULE.V1.ANALYSIS_SCHEMA, MODULE.B_ANALYSIS_SCHEMA)
        self.assertEqual(
            MODULE.B_DEFAULT_OUTPUT_JSON.name,
            "same_call_confirmation_b_analysis.json",
        )
        self.assertEqual(
            MODULE.B_DEFAULT_OUTPUT_MD.name,
            "same_call_confirmation_b_analysis.md",
        )
        self.assertNotIn("jobs", MODULE.V1.ARTIFACT_PROTOCOL_CORE)

    def test_scientific_thresholds_bootstrap_holm_and_three_gates_are_unchanged(self):
        self.assertEqual(MODULE.V1.NI_MARGIN, 0.01)
        self.assertEqual(MODULE.V1.BOOTSTRAP_SAMPLES, 10_000)
        self.assertEqual(MODULE.V1.BOOTSTRAP_SEED, 20_260_715)
        self.assertEqual(len(MODULE.V1.SUPERIORITY_COMPARATORS), 6)
        self.assertTrue(
            {
                "unit_suite",
                "engineering_smoke",
                "common_arm_reproducibility",
                "repeated_arm_replay",
                "future_suffix_metamorphic",
                "rng_isolation",
                MODULE.B_SMOKE_PREFLIGHT_KIND,
            }.issubset(MODULE.V1.REQUIRED_PREFLIGHT_KINDS)
        )
        self.assertEqual(
            MODULE.V1.SUPERIORITY_COMPARATORS,
            (
                "bootstrap_only",
                "exact_even_G4",
                "exact_even_G5",
                "random_G5",
                "js_cap_G5",
                "context_no_reactivation_B25",
            ),
        )
        source = inspect.getsource(MODULE._ORIGINAL_ANALYZE_ARTIFACTS)
        self.assertIn('>= -0.005', source)
        self.assertIn('> -0.01', source)
        self.assertIn('p_greater"] < 0.05', source)
        pristine = MODULE._load_frozen_v1()
        self.assertEqual(
            MODULE.V1._holm_adjust.__code__.co_code,
            pristine._holm_adjust.__code__.co_code,
        )
        self.assertEqual(
            MODULE.V1._holm_adjust.__code__.co_consts,
            pristine._holm_adjust.__code__.co_consts,
        )

    def test_exact_mitm_matches_frozen_enumerator_bit_for_bit(self):
        cases = [
            [],
            [0.0, -0.0],
            [0.1],
            [0.25, -0.25],
            [0.0, 0.1, -0.03],
            [1e-16, 2e-16, -3e-16],
        ]
        rng = random.Random(20260715)
        for size in range(1, 13):
            for _ in range(25):
                cases.append([rng.uniform(-0.1, 0.1) for _ in range(size)])
        for values in cases:
            with self.subTest(values=values):
                self.assertEqual(
                    MODULE._exact_sign_flip_meet_in_the_middle(values),
                    MODULE._ORIGINAL_EXACT_SIGN_FLIP(values),
                )

    def test_exact_mitm_handles_forty_roots_without_approximation(self):
        result = MODULE._exact_sign_flip_b([0.01] * 40)
        self.assertEqual(result["method"], "exact_root_seed_sign_flip")
        self.assertEqual(result["nonzero_root_seeds"], 40)
        self.assertEqual(result["ties_omitted"], 0)
        self.assertEqual(result["assignments"], 1 << 40)
        self.assertEqual(result["p_greater"], 1.0 / (1 << 40))

    def test_b_config_validation_is_fail_closed(self):
        config = _b_config()
        MODULE._validate_config_b(config)

        bad = copy.deepcopy(config)
        bad["root_derivation"]["domain"] = "post-hoc-domain"
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "root_derivation"):
            MODULE._validate_config_b(bad)

        bad = copy.deepcopy(config)
        bad["provenance"]["b_fresh_root_runs_observed_at_freeze"] = 1
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "counters"):
            MODULE._validate_config_b(bad)

        bad = copy.deepcopy(config)
        bad["provenance"]["pool_with_a2"] = True
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "standalone"):
            MODULE._validate_config_b(bad)

        bad = copy.deepcopy(config)
        bad["frozen_artifacts"]["analyzer_b"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "self-bind"):
            MODULE._validate_config_b(bad)

        bad = copy.deepcopy(config)
        bad["protocol"]["noninferiority_margin"] = 0.02
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "margin"):
            MODULE._validate_config_b(bad)

        bad = copy.deepcopy(config)
        bad["execution"]["jobs_per_scenario"] = 0
        with self.assertRaisesRegex(MODULE.SameCallConfirmationError, "jobs_per_scenario"):
            MODULE._validate_config_b(bad)

    def test_artifact_jobs_must_match_frozen_b_execution_value(self):
        config = _b_config()
        artifact = {"protocol": {"jobs": 30}}
        with mock.patch.object(
            MODULE, "_ORIGINAL_VALIDATE_ARTIFACT_PROTOCOL", return_value=None
        ):
            MODULE._validate_artifact_protocol_b(artifact, "narrow_r020", config, {})
            artifact["protocol"]["jobs"] = 29
            with self.assertRaisesRegex(
                MODULE.SameCallConfirmationError, "jobs differs"
            ):
                MODULE._validate_artifact_protocol_b(
                    artifact, "narrow_r020", config, {}
                )

    def test_artifact_root_domain_and_source_are_bound(self):
        artifact = {
            "split_protocol": {
                "canonical_name": MODULE.V1.SPLIT,
                "preregistered_seeds": list(MODULE.B_ROOTS),
                "seed_derivation_source_sha256": (
                    MODULE.B_DERIVATION_SOURCE_SHA256
                ),
                "seed_derivation_domain": MODULE.B_DOMAIN,
                "seed_derivation": (
                    f"source={MODULE.B_DERIVATION_SOURCE_SHA256}; "
                    f"domain={MODULE.B_DOMAIN}; i=0..39"
                ),
                "complete_same_call_method_family_required": True,
                "complete_workload_family_required": True,
                "artifact_overwrite_permitted": False,
            }
        }
        MODULE._validate_b_artifact_provenance(artifact)
        artifact["split_protocol"]["seed_derivation_domain"] = "wrong"
        with self.assertRaisesRegex(
            MODULE.SameCallConfirmationError, "provenance differs"
        ):
            MODULE._validate_b_artifact_provenance(artifact)

    def test_provenance_files_and_target_attestation_are_hash_verified(self):
        config = _b_config()
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            attestation = directory / "attestation.json"
            projection = {"host": "synthetic-b-host", "fixture": True}
            projection_sha = MODULE._canonical_sha256(projection)
            backbone_names = {
                "period_on_sim",
                "checkpoint_file",
                "checkpoint_params",
                "narrow_map",
                "regular_map",
            }
            b_control_names = {
                "runner_b",
                "analyzer_b",
                "launcher_b",
                "builder_b",
                "capture_environment_b",
            }
            excluded = backbone_names | b_control_names | {
                "protocol_b",
                "predecessor_a2_config",
            }
            attestation.write_text(
                json.dumps(
                    {
                        "schema": "dai.same-call-environment-attestation/b",
                        "status": "complete",
                        "passed": True,
                        "created_before_experiment_b": True,
                        "execution_host": "synthetic-b-host",
                        "b_fresh_root_runs_observed": 0,
                        "b_effect_estimates_computed": 0,
                        "b_method_rankings_inspected": 0,
                        "b_effect_inference_performed": False,
                        "prior_a2_outcomes_known": True,
                        "standalone_primary_analysis": True,
                        "pool_with_a2": False,
                        "public_preregistration": False,
                        "protocol": config["frozen_artifacts"]["protocol_b"],
                        "predecessor_config": {
                            "path": config["frozen_artifacts"][
                                "predecessor_a2_config"
                            ]["path"],
                            "sha256": config["provenance"][
                                "predecessor_a2_config_sha256"
                            ],
                        },
                        "experiment_b_contract": {
                            "root_seeds": list(MODULE.B_ROOTS),
                            "root_count": MODULE.B_ROOT_COUNT,
                            "roots_disjoint_from_a1_and_a2": True,
                            "root_derivation": config["root_derivation"],
                            "methods": config["methods"],
                            "workloads": config["workloads"],
                            "scenario_ids": [
                                row["id"] for row in config["scenarios"]
                            ],
                            "runs_per_scenario": MODULE.B_RUNS_PER_SCENARIO,
                            "attempt_ledger_events_per_scenario": (
                                MODULE.B_LEDGER_EVENTS_PER_SCENARIO
                            ),
                            "paired_cells_per_method": (
                                MODULE.B_PAIRED_CELLS_PER_METHOD
                            ),
                            "total_runs": MODULE.B_TOTAL_RUNS,
                        },
                        "environment": {
                            "host": "synthetic-b-host",
                            "host_instance_fingerprint_sha256": "b" * 64,
                        },
                        "environment_compatibility_projection": projection,
                        "environment_compatibility_projection_sha256": (
                            projection_sha
                        ),
                        "zero_b_outcome_checks": [
                            {"path": "results/b", "exists": False}
                        ],
                        "inherited_file_sources": {
                            label: record
                            for label, record in config["frozen_artifacts"].items()
                            if label not in excluded
                        },
                        "backbone_artifacts": {
                            label: config["frozen_artifacts"][label]
                            for label in backbone_names
                        },
                        "b_control_plane_artifacts": {
                            label: config["frozen_artifacts"][label]
                            for label in b_control_names
                        },
                    }
                ),
                encoding="utf-8",
            )
            config["target_environment"] = {
                "execution_host": "synthetic-b-host",
                "path": str(attestation),
                "sha256": _sha(attestation),
                "host_instance_fingerprint_sha256": "b" * 64,
                "compatibility_projection_sha256": projection_sha,
            }
            config["preflight_evidence"][MODULE.B_ENVIRONMENT_PREFLIGHT_KIND].update(
                {
                    "path": str(attestation),
                    "sha256": _sha(attestation),
                }
            )
            freeze = directory / "freeze.json"
            freeze.write_text(
                json.dumps(
                    {
                        "schema": MODULE.B_FREEZE_SCHEMA,
                        "b_effect_estimates_computed": 0,
                        "b_fresh_root_runs_observed": 0,
                        "b_method_rankings_inspected": 0,
                        "effect_inference_performed": False,
                        "prior_a2_outcomes_known": True,
                        "standalone_primary_analysis": True,
                        "pool_with_a2": False,
                        "root_derivation": config["root_derivation"],
                        "confirmation_roots": list(MODULE.B_ROOTS),
                        "methods": config["methods"],
                        "workloads": config["workloads"],
                        "scenarios": config["scenarios"],
                        "execution": config["execution"],
                        "file_artifacts": config["frozen_artifacts"],
                        "preflight_evidence": config["preflight_evidence"],
                        "protocol": config["frozen_artifacts"]["protocol_b"],
                        "b_engineering_smoke": config["preflight_evidence"][
                            MODULE.B_SMOKE_PREFLIGHT_KIND
                        ],
                        "target_environment": config["target_environment"],
                        "predecessor_a2_config": {
                            "path": config["frozen_artifacts"][
                                "predecessor_a2_config"
                            ]["path"],
                            "sha256": config["provenance"][
                                "predecessor_a2_config_sha256"
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            config["provenance"]["implementation_freeze_path"] = str(freeze)
            config["provenance"]["implementation_freeze_sha256"] = _sha(freeze)
            MODULE._verify_b_provenance(config, directory / "config.json")
            config["target_environment"]["sha256"] = "0" * 64
            with self.assertRaisesRegex(
                MODULE.SameCallConfirmationError, "file/hash"
            ):
                MODULE._verify_b_provenance(config, directory / "config.json")

    def test_process_identity_correction_keeps_bare_pid_non_gating(self):
        runs = [
            {
                "execution_host": "host",
                "execution_process_id": 7,
                "execution_process_start_ns": 100,
                "run_uuid": "00000000-0000-0000-0000-000000000001",
            },
            {
                "execution_host": "host",
                "execution_process_id": 7,
                "execution_process_start_ns": 200,
                "run_uuid": "00000000-0000-0000-0000-000000000002",
            },
        ]
        original = (
            runs,
            [dict(MODULE.BARE_PID_FAILURE)],
            {"runs": 2, "unique_execution_processes": 1},
        )
        with mock.patch.object(
            MODULE, "_ORIGINAL_NORMALIZE_AND_AUDIT", return_value=original
        ):
            _, failures, totals = MODULE._normalize_and_audit([], {}, "", {})
        self.assertEqual(failures, [])
        self.assertEqual(totals["unique_bare_pids"], 1)
        self.assertEqual(totals["unique_process_instances"], 2)
        self.assertEqual(totals["unique_run_uuids"], 2)
        self.assertFalse(totals["bare_pid_uniqueness_is_gate"])

    def test_duplicate_process_instance_remains_a_hard_failure(self):
        runs = [
            {
                "execution_host": "host",
                "execution_process_id": 7,
                "execution_process_start_ns": 100,
                "run_uuid": "00000000-0000-0000-0000-000000000001",
            },
            {
                "execution_host": "host",
                "execution_process_id": 7,
                "execution_process_start_ns": 100,
                "run_uuid": "00000000-0000-0000-0000-000000000002",
            },
        ]
        original = (
            runs,
            [dict(MODULE.BARE_PID_FAILURE)],
            {"runs": 2, "unique_execution_processes": 1},
        )
        with mock.patch.object(
            MODULE, "_ORIGINAL_NORMALIZE_AND_AUDIT", return_value=original
        ):
            _, failures, _ = MODULE._normalize_and_audit([], {}, "", {})
        self.assertIn(
            {"category": "fresh_process", "check": MODULE.PROCESS_INSTANCE_CHECK},
            failures,
        )

    def test_stale_v1_ledger_error_is_relabelled_for_b(self):
        error = MODULE.SameCallConfirmationError(
            "attempt ledger must contain exactly 480 events"
        )
        with mock.patch.object(
            MODULE, "_ORIGINAL_VERIFY_ATTEMPT_LEDGER", side_effect=error
        ):
            with self.assertRaisesRegex(
                MODULE.SameCallConfirmationError, "exactly 1920 events"
            ):
                MODULE._verify_attempt_ledger_b({}, [], 1)

    def test_report_cardinality_and_markdown_are_relabelled(self):
        report = {
            "schema": "dai.same-call-confirmation-analysis/v1",
            "audit": {
                "passed": True,
                "totals": {"runs": MODULE.B_TOTAL_RUNS},
                "complete_960_run_matrix": False,
            },
            "design": {"root_seeds": [], "total_runs": 960},
        }
        result = MODULE._postprocess_report(report)
        self.assertEqual(result["schema"], MODULE.B_ANALYSIS_SCHEMA)
        self.assertNotIn("complete_960_run_matrix", result["audit"])
        self.assertTrue(result["audit"]["complete_3840_run_matrix"])
        self.assertEqual(result["design"]["n_root_seed_clusters"], 40)
        self.assertEqual(result["design"]["paired_cells_per_method"], 480)
        markdown = MODULE.render_markdown.__globals__["_ORIGINAL_RENDER_MARKDOWN"]
        self.assertTrue(callable(markdown))


if __name__ == "__main__":
    unittest.main()
