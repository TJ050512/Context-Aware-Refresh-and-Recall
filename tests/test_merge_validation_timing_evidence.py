import copy
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/merge_validation_timing_evidence.py"
SPEC = importlib.util.spec_from_file_location(
    "merge_validation_timing_evidence", SCRIPT
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _sha(character):
    return character * 64


def _validation(candidate=True):
    causal = {"passed": True, "checks": {"frozen": True}, "effect": 0.021}
    near = {"permitted": False, "checks": {"ci": False}}
    pure = {
        "passed": False,
        "selected_top_method": "random_B25",
        "runner_up_method": "causal_block_B25",
    }
    return {
        "schema": MODULE.VALIDATION_SCHEMA,
        "sources": [
            {"label": f"validation-{index}", "sha256": hex(index + 1)[2:] * 64}
            for index in range(4)
        ],
        "evidence": {
            "source_evidence_class": "validation_v2",
            "fresh_validation_v2": True,
        },
        "audit": {"passed": True, "integrity_gate_passed": True},
        "reproducibility": {
            "checkpoint": {
                "file_sha256": MODULE.EXPECTED_CHECKPOINT_FILE_SHA256,
                "params_sha256": MODULE.EXPECTED_CHECKPOINT_PARAMS_SHA256,
            },
            "simulator_sha256": MODULE.EXPECTED_SIMULATOR_SHA256,
            "frozen_validation_v2_lock": {
                "root_seeds": list(MODULE.EXPECTED_VALIDATION_SEEDS),
                "formal_methods": list(MODULE.EXPECTED_FORMAL_METHODS),
                "scored_horizon": 2000,
                "decision_window": 20,
                "warmup_time": 200,
                "release_interval_per_agent": 110,
                "guard_suffix_tasks_per_agent": 4,
                "sigma": 0.75,
                "context_memory": {
                    "recall_threshold": 0.05,
                    "recall_margin": 0.02,
                    "absolute_score_gate": 0.10,
                    "min_gap_windows": 6,
                    "maintenance_age_windows": 25,
                    "maintenance_stability_gate": 0.20,
                },
            },
        },
        "preregistered_go_no_go": {
            "name": "frozen_combined_validation_v2_decision_gates",
            "context_validation_candidate_passed": candidate,
            "context_validation_candidate": {
                "passed": candidate,
                "checks": {"unchanged": candidate},
                "generator_call_reduction_vs_exact_B25": 0.84,
            },
            "causal_quality_go": causal,
            "context_near_exact_language": near,
            "pure_throughput_best_evaluated_controller": pure,
        },
    }


def _timing(passed=True):
    return {
        "schema": MODULE.TIMING_SCHEMA,
        "status": "complete",
        "claim_scope": {
            "supported": MODULE.EXPECTED_TIMING_SUPPORTED_SCOPE,
            "throughput_inference_permitted": False,
            "global_lmapf_sota_inference_permitted": False,
        },
        "config": {
            "path": "/workspace/configs/context_exclusive_timing_protocol_v1.json",
            "sha256": MODULE.EXPECTED_TIMING_CONFIG_SHA256,
        },
        "audit": {
            "passed": True,
            "timing_evidence_valid": True,
            "paired_cells": 60,
            "runs": 120,
            "root_seed_clusters": 5,
            "artifacts": [
                {"label": label, "sha256": str(index + 5) * 64}
                for index, label in enumerate(sorted(MODULE.EXPECTED_TIMING_SOURCE_LABELS))
            ],
        },
        "primary_timing_gate": {
            "threshold": 0.80,
            "pooled_reduction": 0.85 if passed else 0.75,
            "mean_paired_cell_reduction": 0.84,
            "pooled_reduction_passed": passed,
            "mean_reduction_passed": True,
            "passed": passed,
            "decision": (
                "PASS_GENERATOR_TIME_REDUCTION_GATE"
                if passed
                else "FAIL_GENERATOR_TIME_REDUCTION_GATE"
            ),
        },
    }


def _merge(validation=None, timing=None):
    return MODULE.merge_reports(
        validation or _validation(),
        timing or _timing(),
        validation_analysis_source={"path": "/v.json", "sha256": _sha("a")},
        timing_analysis_source={"path": "/t.json", "sha256": _sha("b")},
        merger_script_sha256=_sha("c"),
    )


class EvidenceMergeTests(unittest.TestCase):
    def test_ready_is_exact_conjunction_and_preserves_conclusions(self):
        validation = _validation()
        expected = copy.deepcopy(
            {
                key: validation["preregistered_go_no_go"][key]
                for key in (
                    "causal_quality_go",
                    "context_near_exact_language",
                    "pure_throughput_best_evaluated_controller",
                )
            }
        )
        report = _merge(validation=validation)
        self.assertTrue(report["context_full_efficiency_claim_ready"])
        self.assertEqual(report["preserved_validation_conclusions"], expected)
        self.assertFalse(report["merge_rule"]["throughput_statistics_recomputed"])
        for name, value in expected.items():
            digest = hashlib.sha256(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode()
            ).hexdigest()
            self.assertEqual(report["preservation_audit"]["canonical_sha256"][name], digest)

    def test_validation_failure_keeps_full_claim_not_ready(self):
        report = _merge(validation=_validation(candidate=False))
        self.assertFalse(report["context_full_efficiency_claim_ready"])
        self.assertEqual(
            report["context_full_efficiency_claim"]["status"],
            "not_ready_validation_candidate_failed",
        )

    def test_timing_failure_keeps_full_claim_not_ready(self):
        report = _merge(timing=_timing(passed=False))
        self.assertFalse(report["context_full_efficiency_claim_ready"])
        self.assertEqual(
            report["context_full_efficiency_claim"]["status"],
            "not_ready_exclusive_timing_gate_failed",
        )

    def test_nonfresh_validation_is_rejected(self):
        validation = _validation()
        validation["evidence"]["fresh_validation_v2"] = False
        with self.assertRaisesRegex(MODULE.EvidenceMergeError, "not fresh"):
            _merge(validation=validation)

    def test_timing_scope_cannot_allow_throughput(self):
        timing = _timing()
        timing["claim_scope"]["throughput_inference_permitted"] = True
        with self.assertRaisesRegex(MODULE.EvidenceMergeError, "permits throughput"):
            _merge(timing=timing)

    def test_validation_method_mismatch_is_rejected(self):
        validation = _validation()
        validation["reproducibility"]["frozen_validation_v2_lock"][
            "formal_methods"
        ].remove("context_memory_B25")
        with self.assertRaisesRegex(MODULE.EvidenceMergeError, "method family"):
            _merge(validation=validation)

    def test_timing_protocol_hash_mismatch_is_rejected(self):
        timing = _timing()
        timing["config"]["sha256"] = _sha("0")
        with self.assertRaisesRegex(MODULE.EvidenceMergeError, "frozen protocol"):
            _merge(timing=timing)

    def test_inconsistent_timing_boolean_is_rejected(self):
        timing = _timing()
        timing["primary_timing_gate"]["passed"] = False
        with self.assertRaisesRegex(MODULE.EvidenceMergeError, "internally inconsistent"):
            _merge(timing=timing)

    def test_every_upstream_sha_is_retained(self):
        validation = _validation()
        timing = _timing()
        report = _merge(validation=validation, timing=timing)
        self.assertEqual(
            report["provenance"]["validation_upstream_sources"],
            validation["sources"],
        )
        self.assertEqual(
            report["provenance"]["timing_upstream_sources"],
            timing["audit"]["artifacts"],
        )
        self.assertEqual(report["provenance"]["merger_script_sha256"], _sha("c"))


if __name__ == "__main__":
    unittest.main()
