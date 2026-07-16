#!/usr/bin/env python3
"""Merge frozen validation and exclusive-timing decisions without reanalysis.

The merger performs identity, provenance, scope, and Boolean-consistency
checks only.  It never reads runner artifacts and never recomputes throughput
statistics.  Full context-efficiency readiness is the conjunction of the
fresh validation candidate gate and the separate exclusive timing gate.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


VALIDATION_SCHEMA = "dai.combined-validation-v2-analysis/v1"
TIMING_SCHEMA = "dai.context-exclusive-timing-analysis/v1"
MERGED_SCHEMA = "dai.validation-timing-evidence-merge/v1"
EXPECTED_TIMING_CONFIG_SHA256 = (
    "aff4a620806faa0a34883dbe783b26aa4df7a0f5513b1cdfc14a535febf5a543"
)
EXPECTED_CHECKPOINT_FILE_SHA256 = (
    "e4d918075c9ea0e5be795572c16c64a843da2780294a407a190b989298008c8d"
)
EXPECTED_CHECKPOINT_PARAMS_SHA256 = (
    "6f95c14a6afad6484a525f68e9809cf7c8a86fe48878a3d80abea67dd94abbac"
)
EXPECTED_SIMULATOR_SHA256 = (
    "9e4b54722d67598f13f1bc2d4d0fb4121a94f79962923c184c1d269225e8c1a5"
)
EXPECTED_VALIDATION_SEEDS = (
    320019,
    241771,
    827130,
    693142,
    741084,
    12102,
    133633,
    876480,
    50620,
    131545,
)
EXPECTED_FORMAL_METHODS = (
    "uniform",
    "bootstrap_only",
    "always",
    "exact_even_B25",
    "period_80",
    "random_B25",
    "js_B25",
    "js_cap_B25",
    "context_memory_B25",
    "throughput_drop_B25",
    "causal_block_B25",
    "proposed_cohort_B25",
    "proposed_no_cohort_B25",
)
EXPECTED_TIMING_SOURCE_LABELS = frozenset(
    {"narrow_r020", "narrow_r035", "regular_r020", "regular_r035"}
)
EXPECTED_TIMING_SUPPORTED_SCOPE = (
    "generator_seconds efficiency for context_memory_B25 versus "
    "exact_even_B25 on the frozen four-scenario development timing matrix"
)


class EvidenceMergeError(ValueError):
    """The two analyses cannot be combined under the frozen evidence rule."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _object_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceMergeError(message)


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceMergeError(f"{field} must be Boolean")
    return value


def _validate_source_records(
    records: Any, *, field: str, expected_count: int, expected_labels: set[str] | None = None
) -> list[dict[str, Any]]:
    _require(isinstance(records, list), f"{field} must be a list")
    _require(len(records) == expected_count, f"{field} must contain {expected_count} records")
    copied: list[dict[str, Any]] = []
    labels: list[str] = []
    for index, record in enumerate(records):
        _require(isinstance(record, Mapping), f"{field}[{index}] must be an object")
        digest = record.get("sha256")
        _require(_is_sha256(digest), f"{field}[{index}].sha256 is invalid")
        label = record.get("label")
        _require(isinstance(label, str) and bool(label), f"{field}[{index}].label is invalid")
        labels.append(label)
        copied.append(copy.deepcopy(dict(record)))
    _require(len(set(labels)) == expected_count, f"{field} labels must be unique")
    if expected_labels is not None:
        _require(set(labels) == expected_labels, f"{field} scenario labels do not match")
    return copied


def _validate_validation(report: Mapping[str, Any]) -> dict[str, Any]:
    _require(report.get("schema") == VALIDATION_SCHEMA, "validation schema mismatch")
    evidence = report.get("evidence")
    _require(isinstance(evidence, Mapping), "validation evidence metadata is missing")
    _require(
        evidence.get("source_evidence_class") == "validation_v2"
        and evidence.get("fresh_validation_v2") is True,
        "validation analysis is not fresh validation-v2 evidence",
    )
    audit = report.get("audit")
    _require(isinstance(audit, Mapping), "validation audit is missing")
    _require(
        audit.get("passed") is True and audit.get("integrity_gate_passed") is True,
        "validation integrity audit did not pass",
    )
    reproducibility = report.get("reproducibility")
    _require(isinstance(reproducibility, Mapping), "validation reproducibility lock is missing")
    checkpoint = reproducibility.get("checkpoint", {})
    _require(
        checkpoint.get("file_sha256") == EXPECTED_CHECKPOINT_FILE_SHA256
        and checkpoint.get("params_sha256") == EXPECTED_CHECKPOINT_PARAMS_SHA256,
        "validation checkpoint does not match the frozen treatment",
    )
    _require(
        reproducibility.get("simulator_sha256") == EXPECTED_SIMULATOR_SHA256,
        "validation simulator does not match the frozen treatment",
    )
    lock = reproducibility.get("frozen_validation_v2_lock")
    _require(isinstance(lock, Mapping), "validation protocol lock is missing")
    _require(
        tuple(lock.get("root_seeds", ())) == EXPECTED_VALIDATION_SEEDS,
        "validation seed protocol mismatch",
    )
    _require(
        tuple(lock.get("formal_methods", ())) == EXPECTED_FORMAL_METHODS,
        "validation method family mismatch",
    )
    for field, expected in (
        ("scored_horizon", 2000),
        ("decision_window", 20),
        ("warmup_time", 200),
        ("release_interval_per_agent", 110),
        ("guard_suffix_tasks_per_agent", 4),
        ("sigma", 0.75),
    ):
        _require(lock.get(field) == expected, f"validation protocol mismatch: {field}")
    context = lock.get("context_memory", {})
    for field, expected in (
        ("recall_threshold", 0.05),
        ("recall_margin", 0.02),
        ("absolute_score_gate", 0.10),
        ("min_gap_windows", 6),
        ("maintenance_age_windows", 25),
        ("maintenance_stability_gate", 0.20),
    ):
        _require(context.get(field) == expected, f"validation context protocol mismatch: {field}")

    gate = report.get("preregistered_go_no_go")
    _require(isinstance(gate, Mapping), "validation gate is missing")
    _require(
        gate.get("name") == "frozen_combined_validation_v2_decision_gates",
        "validation gate identity mismatch",
    )
    candidate = _require_bool(
        gate.get("context_validation_candidate_passed"),
        "validation.context_validation_candidate_passed",
    )
    candidate_detail = gate.get("context_validation_candidate")
    _require(isinstance(candidate_detail, Mapping), "validation candidate detail is missing")
    _require(
        candidate_detail.get("passed") is candidate,
        "validation candidate Boolean is internally inconsistent",
    )
    required_conclusions = (
        "causal_quality_go",
        "context_near_exact_language",
        "pure_throughput_best_evaluated_controller",
    )
    for field in required_conclusions:
        _require(isinstance(gate.get(field), Mapping), f"validation conclusion is missing: {field}")
    return {
        "candidate": candidate,
        "candidate_detail": copy.deepcopy(dict(candidate_detail)),
        "conclusions": {
            field: copy.deepcopy(dict(gate[field])) for field in required_conclusions
        },
        "upstream_sources": _validate_source_records(
            report.get("sources"), field="validation.sources", expected_count=4
        ),
    }


def _validate_timing(report: Mapping[str, Any]) -> dict[str, Any]:
    _require(report.get("schema") == TIMING_SCHEMA, "timing schema mismatch")
    _require(report.get("status") == "complete", "timing analysis is incomplete")
    scope = report.get("claim_scope")
    _require(isinstance(scope, Mapping), "timing claim scope is missing")
    _require(
        scope.get("supported") == EXPECTED_TIMING_SUPPORTED_SCOPE,
        "timing method or protocol scope mismatch",
    )
    _require(
        scope.get("throughput_inference_permitted") is False
        and scope.get("global_lmapf_sota_inference_permitted") is False,
        "timing scope improperly permits throughput or global-SOTA inference",
    )
    config = report.get("config")
    _require(isinstance(config, Mapping), "timing protocol provenance is missing")
    _require(
        config.get("sha256") == EXPECTED_TIMING_CONFIG_SHA256,
        "timing analysis was not produced under the frozen protocol config",
    )
    audit = report.get("audit")
    _require(isinstance(audit, Mapping), "timing audit is missing")
    _require(
        audit.get("passed") is True
        and audit.get("timing_evidence_valid") is True
        and audit.get("paired_cells") == 60
        and audit.get("runs") == 120
        and audit.get("root_seed_clusters") == 5,
        "timing evidence audit is invalid or incomplete",
    )
    primary = report.get("primary_timing_gate")
    _require(isinstance(primary, Mapping), "primary timing gate is missing")
    _require(primary.get("threshold") == 0.80, "timing threshold mismatch")
    pooled = _require_bool(primary.get("pooled_reduction_passed"), "timing pooled gate")
    mean = _require_bool(primary.get("mean_reduction_passed"), "timing mean gate")
    passed = _require_bool(primary.get("passed"), "timing primary gate")
    _require(passed is (pooled and mean), "timing primary gate is internally inconsistent")
    expected_decision = (
        "PASS_GENERATOR_TIME_REDUCTION_GATE"
        if passed
        else "FAIL_GENERATOR_TIME_REDUCTION_GATE"
    )
    _require(primary.get("decision") == expected_decision, "timing decision label mismatch")
    return {
        "passed": passed,
        "primary_gate": copy.deepcopy(dict(primary)),
        "config": copy.deepcopy(dict(config)),
        "upstream_sources": _validate_source_records(
            audit.get("artifacts"),
            field="timing.audit.artifacts",
            expected_count=4,
            expected_labels=set(EXPECTED_TIMING_SOURCE_LABELS),
        ),
    }


def merge_reports(
    validation: Mapping[str, Any],
    timing: Mapping[str, Any],
    *,
    validation_analysis_source: Mapping[str, Any],
    timing_analysis_source: Mapping[str, Any],
    merger_script_sha256: str,
) -> dict[str, Any]:
    """Merge two already-complete decisions using a frozen logical AND."""

    for label, source in (
        ("validation analysis", validation_analysis_source),
        ("timing analysis", timing_analysis_source),
    ):
        _require(isinstance(source, Mapping), f"{label} source metadata is missing")
        _require(_is_sha256(source.get("sha256")), f"{label} SHA256 is invalid")
    _require(_is_sha256(merger_script_sha256), "merger script SHA256 is invalid")
    validation_checked = _validate_validation(validation)
    timing_checked = _validate_timing(timing)
    ready = validation_checked["candidate"] and timing_checked["passed"]
    conclusions = validation_checked["conclusions"]
    conclusion_hashes = {
        name: _object_sha256(value) for name, value in conclusions.items()
    }
    return {
        "schema": MERGED_SCHEMA,
        "status": "complete",
        "merge_rule": {
            "definition": (
                "context_validation_candidate_passed AND "
                "exclusive_timing.primary_timing_gate.passed"
            ),
            "result_dependent_threshold_changes": False,
            "throughput_statistics_recomputed": False,
        },
        "context_validation_candidate_passed": validation_checked["candidate"],
        "exclusive_timing_primary_gate_passed": timing_checked["passed"],
        "context_full_efficiency_claim_ready": ready,
        "context_full_efficiency_claim": {
            "ready": ready,
            "status": (
                "full_efficiency_claim_ready"
                if ready
                else "not_ready_validation_candidate_failed"
                if not validation_checked["candidate"]
                else "not_ready_exclusive_timing_gate_failed"
            ),
            "scope": (
                "Full efficiency combines the unchanged validation throughput/call "
                "candidate decision with generator-only exclusive timing. It is not "
                "a locked-test or global LMAPF SOTA claim."
            ),
        },
        "validation_candidate_detail_unchanged": validation_checked[
            "candidate_detail"
        ],
        "exclusive_timing_gate_unchanged": timing_checked["primary_gate"],
        "preserved_validation_conclusions": conclusions,
        "preservation_audit": {
            "copied_without_recomputation": True,
            "canonical_sha256": conclusion_hashes,
        },
        "provenance": {
            "merger_script_sha256": merger_script_sha256,
            "validation_analysis": copy.deepcopy(dict(validation_analysis_source)),
            "exclusive_timing_analysis": copy.deepcopy(dict(timing_analysis_source)),
            "validation_upstream_sources": validation_checked["upstream_sources"],
            "timing_upstream_sources": timing_checked["upstream_sources"],
            "timing_protocol_config": timing_checked["config"],
        },
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    state = report["context_full_efficiency_claim"]
    preserved = report["preserved_validation_conclusions"]
    return "\n".join(
        [
            "# Validation + exclusive timing evidence merge",
            "",
            f"Full context-efficiency claim: **{'READY' if state['ready'] else 'NOT READY'}**",
            "",
            f"- Validation candidate: {report['context_validation_candidate_passed']}",
            f"- Exclusive timing gate: {report['exclusive_timing_primary_gate_passed']}",
            f"- Status: `{state['status']}`",
            "- Throughput statistics recomputed: false",
            "",
            "The causal, near-exact, and pure-throughput conclusions below are "
            "copied byte-semantically from the validation analysis; the merger does "
            "not reevaluate them.",
            "",
            f"- Causal quality: {preserved['causal_quality_go'].get('passed')}",
            f"- Near-exact language: {preserved['context_near_exact_language'].get('permitted')}",
            f"- Pure-throughput claim: {preserved['pure_throughput_best_evaluated_controller'].get('passed')}",
        ]
    ) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-analysis", type=Path, required=True)
    parser.add_argument("--timing-analysis", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    for output in (args.output_json, args.output_md):
        if output.exists():
            raise FileExistsError(f"refusing to overwrite merged evidence: {output}")
    validation = json.loads(args.validation_analysis.read_text(encoding="utf-8"))
    timing = json.loads(args.timing_analysis.read_text(encoding="utf-8"))
    script_path = Path(__file__).resolve()
    report = merge_reports(
        validation,
        timing,
        validation_analysis_source={
            "path": str(args.validation_analysis.resolve()),
            "sha256": _file_sha256(args.validation_analysis),
        },
        timing_analysis_source={
            "path": str(args.timing_analysis.resolve()),
            "sha256": _file_sha256(args.timing_analysis),
        },
        merger_script_sha256=_file_sha256(script_path),
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    args.output_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["context_full_efficiency_claim"], indent=2, sort_keys=True))
    print(f"merged_json={args.output_json}")
    print(f"merged_md={args.output_md}")


if __name__ == "__main__":
    main()
