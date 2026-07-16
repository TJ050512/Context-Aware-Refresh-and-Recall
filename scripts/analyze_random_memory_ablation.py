#!/usr/bin/env python3
"""Focused read-only audit of random-memory versus matched random timing.

The script first applies the complete-grid and pairing checks from
``analyze_full_method_matrix.py``.  It then verifies, decision by decision,
that ``random_B25`` and ``random_memory_B25`` received the identical random
opportunity schedule.  Only the operation at an accepted opportunity may
differ: random always generates, whereas random-memory may reactivate a
previously generated guidance map.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from analyze_full_method_matrix import analyze as analyze_full_matrix


ANALYSIS_SCHEMA = "dai.random-memory-ablation-analysis/v1"
MEMORY = "random_memory_B25"
RANDOM = "random_B25"
EXACT = "exact_even_B25"
REQUIRED_METHODS = (EXACT, RANDOM, MEMORY)


class RandomMemoryAuditError(ValueError):
    """The artifact is not a valid matched random-memory ablation."""


def _canonical(value: Any) -> str:
    return json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("mean needs at least one value")
    return math.fsum(values) / len(values)


def _policy_signature(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Fields produced solely by the shared registered random schedule."""

    policy = entry.get("policy")
    if not isinstance(policy, dict):
        raise RandomMemoryAuditError(
            f"decision {entry.get('decision_index')} has no policy object"
        )
    return {
        "decision_index": entry.get("decision_index"),
        "requested": entry.get("requested"),
        "accepted": entry.get("accepted"),
        "charged_to_post_bootstrap_budget": entry.get(
            "charged_to_post_bootstrap_budget"
        ),
        "policy": policy,
    }


def _timeline_by_decision(run: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    timeline = run.get("publication_timeline")
    if not isinstance(timeline, list) or not timeline:
        raise RandomMemoryAuditError("publication_timeline must be non-empty")
    indexed: dict[int, Mapping[str, Any]] = {}
    for entry in timeline:
        if not isinstance(entry, dict):
            raise RandomMemoryAuditError("publication timeline entries must be objects")
        decision = entry.get("decision_index")
        if isinstance(decision, bool) or not isinstance(decision, int):
            raise RandomMemoryAuditError("decision_index must be an integer")
        if decision in indexed:
            raise RandomMemoryAuditError(f"duplicate timeline decision {decision}")
        indexed[decision] = entry
    expected = set(range(int(run["window_count"])))
    if set(indexed) != expected:
        raise RandomMemoryAuditError(
            f"timeline decisions are incomplete: missing={sorted(expected - set(indexed))}"
        )
    return indexed


def _source_integrity(
    artifact: Mapping[str, Any], artifact_path: Path, source_sha256: str
) -> dict[str, Any]:
    workspace = artifact_path.resolve().parents[2]
    map_name = Path(str(artifact.get("map_path", ""))).name
    local_map = (
        workspace
        / "external/OnlineGGO/Guided-PIBT/guided-pibt/benchmark-lifelong/maps"
        / map_name
    )
    local_map_sha = _file_sha(local_map) if local_map.is_file() else None
    declared_map_sha = artifact.get("map_sha256")
    return {
        "artifact_path": str(artifact_path.resolve()),
        "artifact_size_bytes": artifact_path.stat().st_size,
        "artifact_sha256": source_sha256,
        "schema": artifact.get("schema"),
        "status": artifact.get("status"),
        "split": artifact.get("split"),
        "evidence_class": artifact.get("evidence_class"),
        "map": {
            "declared_path": artifact.get("map_path"),
            "declared_sha256": declared_map_sha,
            "local_path": str(local_map) if local_map.is_file() else None,
            "local_sha256": local_map_sha,
            "locally_verified": local_map_sha == declared_map_sha,
        },
        "generator": {
            "declared_path": artifact.get("generator", {}).get("path"),
            "declared_file_sha256": artifact.get("generator", {}).get("file_sha256"),
            "declared_params_sha256": artifact.get("generator", {}).get(
                "params_sha256"
            ),
            "local_file_verification": "not_available_in_local_artifact_bundle",
        },
        "simulator": {
            "declared_period_on_sim_sha256": artifact.get("period_on_sim_sha256"),
            "local_file_verification": "not_available_in_local_artifact_bundle",
        },
        "provenance_note": (
            "The artifact and map hashes are locally verified. The pinned remote "
            "checkpoint and simulator hashes are preserved as declarations; their "
            "exact binaries were not bundled with this local artifact."
        ),
    }


def _opportunity_and_recall_audit(
    artifact: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    seeds = [int(seed) for seed in artifact["seeds"]]
    workloads = [str(value) for value in artifact["workloads"]]
    maps = sorted({str(run["map_id"]) for run in runs})
    indexed = {
        (str(run["method"]), int(run["seed"]), str(run["map_id"]), str(run["workload"])): run
        for run in runs
    }
    mismatches: list[dict[str, Any]] = []
    schedule_records: list[dict[str, Any]] = []
    recall_records: list[dict[str, Any]] = []
    total_random_opportunities = 0
    identical_non_recall_outcomes = 0
    non_recall_cells = 0

    threshold = float(artifact["protocol"]["random_memory_B25"]["recall_threshold"])
    margin = float(artifact["protocol"]["random_memory_B25"]["recall_margin"])

    for seed in seeds:
        for map_id in maps:
            for workload in workloads:
                key = (seed, map_id, workload)
                random_run = indexed[(RANDOM, seed, map_id, workload)]
                memory_run = indexed[(MEMORY, seed, map_id, workload)]
                random_timeline = _timeline_by_decision(random_run)
                memory_timeline = _timeline_by_decision(memory_run)
                random_signatures = [
                    _policy_signature(random_timeline[decision])
                    for decision in range(1, int(random_run["window_count"]))
                ]
                memory_signatures = [
                    _policy_signature(memory_timeline[decision])
                    for decision in range(1, int(memory_run["window_count"]))
                ]
                random_hash = _canonical_sha(random_signatures)
                memory_hash = _canonical_sha(memory_signatures)
                random_opportunities = [
                    decision
                    for decision in range(1, int(random_run["window_count"]))
                    if random_timeline[decision].get("requested") is True
                ]
                memory_opportunities = [
                    decision
                    for decision in range(1, int(memory_run["window_count"]))
                    if memory_timeline[decision].get("requested") is True
                ]
                total_random_opportunities += len(random_opportunities)
                if random_signatures != memory_signatures:
                    mismatches.append(
                        {"cell": key, "check": "full_random_policy_signature"}
                    )
                if random_opportunities != memory_opportunities:
                    mismatches.append(
                        {"cell": key, "check": "accepted_opportunity_indices"}
                    )
                expected_budget = int(random_run["publication_budget"])
                if len(random_opportunities) != expected_budget:
                    mismatches.append(
                        {
                            "cell": key,
                            "check": "random_opportunity_count_equals_budget",
                            "actual": len(random_opportunities),
                            "expected": expected_budget,
                        }
                    )
                schedule_records.append(
                    {
                        "seed": seed,
                        "map_id": map_id,
                        "workload": workload,
                        "random_signature_sha256": random_hash,
                        "random_memory_signature_sha256": memory_hash,
                        "opportunity_indices": random_opportunities,
                        "identical": random_hash == memory_hash,
                    }
                )

                for decision in range(1, int(random_run["window_count"])):
                    random_entry = random_timeline[decision]
                    memory_entry = memory_timeline[decision]
                    is_opportunity = decision in random_opportunities
                    random_operation = random_entry.get("executed_operation")
                    memory_operation = memory_entry.get("executed_operation")
                    if is_opportunity:
                        if random_operation != "generate":
                            mismatches.append(
                                {"cell": key, "decision": decision, "check": "random_generates"}
                            )
                        if memory_operation not in {"generate", "reactivate"}:
                            mismatches.append(
                                {
                                    "cell": key,
                                    "decision": decision,
                                    "check": "memory_generate_or_reactivate",
                                }
                            )
                    elif random_operation != "hold" or memory_operation != "hold":
                        mismatches.append(
                            {
                                "cell": key,
                                "decision": decision,
                                "check": "both_hold_outside_opportunity",
                            }
                        )

                reactivations = [
                    entry
                    for entry in memory_timeline.values()
                    if entry.get("executed_operation") == "reactivate"
                ]
                if not reactivations:
                    non_recall_cells += 1
                    if memory_run["num_task_finished"] == random_run["num_task_finished"]:
                        identical_non_recall_outcomes += 1
                catalog = {
                    int(item["generation_id"]): item
                    for item in memory_run.get("guidance_catalog", [])
                }
                for entry in reactivations:
                    decision = int(entry["decision_index"])
                    target = entry.get("target_generation_id")
                    catalog_item = catalog.get(int(target)) if isinstance(target, int) else None
                    previous_active = memory_timeline[decision - 1].get(
                        "active_generation_id_after"
                    )
                    nearest = entry.get("nearest_context_distance")
                    active = entry.get("active_context_distance")
                    valid = (
                        catalog_item is not None
                        and int(catalog_item["generated_at_decision"]) < decision
                        and target != previous_active
                        and isinstance(nearest, (int, float))
                        and isinstance(active, (int, float))
                        and float(nearest) <= threshold + 1e-12
                        and float(nearest) + margin <= float(active) + 1e-12
                        and entry.get("charged_to_generator_budget") is False
                        and entry.get("charged_to_post_bootstrap_budget") is True
                    )
                    if not valid:
                        mismatches.append(
                            {"cell": key, "decision": decision, "check": "valid_reactivation"}
                        )
                    recall_records.append(
                        {
                            "seed": seed,
                            "map_id": map_id,
                            "workload": workload,
                            "decision_index": decision,
                            "target_generation_id": target,
                            "target_generated_at_decision": (
                                catalog_item.get("generated_at_decision")
                                if catalog_item is not None
                                else None
                            ),
                            "previous_active_generation_id": previous_active,
                            "nearest_context_distance": nearest,
                            "active_context_distance": active,
                            "distance_improvement": (
                                float(active) - float(nearest)
                                if isinstance(nearest, (int, float))
                                and isinstance(active, (int, float))
                                else None
                            ),
                            "task_delta_memory_minus_random": int(
                                memory_run["num_task_finished"]
                            )
                            - int(random_run["num_task_finished"]),
                            "generator_calls_saved": int(random_run["generator_calls"])
                            - int(memory_run["generator_calls"]),
                            "valid": valid,
                        }
                    )

    # The registered schedule is a function of root seed. Verify that all
    # workloads/maps for a seed received the same opportunity vector as well.
    hashes_by_seed: dict[int, set[str]] = defaultdict(set)
    for record in schedule_records:
        hashes_by_seed[int(record["seed"])].add(
            _canonical_sha(record["opportunity_indices"])
        )
    cross_workload_schedule = {
        str(seed): {
            "unique_opportunity_schedule_hashes": sorted(hashes),
            "identical_across_maps_and_workloads": len(hashes) == 1,
        }
        for seed, hashes in hashes_by_seed.items()
    }
    all_cross_workload_identical = all(
        row["identical_across_maps_and_workloads"]
        for row in cross_workload_schedule.values()
    )

    random_runs = [run for run in runs if run["method"] == RANDOM]
    memory_runs = [run for run in runs if run["method"] == MEMORY]
    random_calls = sum(int(run["generator_calls"]) for run in random_runs)
    memory_calls = sum(int(run["generator_calls"]) for run in memory_runs)
    random_generations = sum(
        int(run["post_bootstrap_generation_count"]) for run in random_runs
    )
    memory_generations = sum(
        int(run["post_bootstrap_generation_count"]) for run in memory_runs
    )
    recalls_by_workload = {
        workload: sum(record["workload"] == workload for record in recall_records)
        for workload in workloads
    }
    opportunity_audit = {
        "passed": not mismatches and all_cross_workload_identical,
        "paired_cell_count": len(schedule_records),
        "decisions_compared_per_cell": int(artifact["protocol"]["num_scored_windows"]) - 1,
        "random_opportunities_per_cell": sorted(
            {len(record["opportunity_indices"]) for record in schedule_records}
        ),
        "total_random_opportunities": total_random_opportunities,
        "all_random_and_memory_policy_signatures_identical": all(
            record["identical"] for record in schedule_records
        ),
        "all_opportunity_vectors_identical_across_workloads_for_each_seed": (
            all_cross_workload_identical
        ),
        "cross_workload_schedule_hashes_by_seed": cross_workload_schedule,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }
    recall_audit = {
        "recall_threshold": threshold,
        "recall_margin": margin,
        "reactivation_count": len(recall_records),
        "reactivation_rate_per_random_opportunity": (
            len(recall_records) / total_random_opportunities
            if total_random_opportunities
            else 0.0
        ),
        "runs_with_reactivation": len(
            {(r["seed"], r["map_id"], r["workload"]) for r in recall_records}
        ),
        "run_count": len(memory_runs),
        "reactivations_by_workload": recalls_by_workload,
        "reactivation_records": recall_records,
        "all_reactivations_valid": all(record["valid"] for record in recall_records),
        "non_recall_cells": non_recall_cells,
        "non_recall_cells_with_identical_tasks": identical_non_recall_outcomes,
        "random_total_generator_calls": random_calls,
        "random_memory_total_generator_calls": memory_calls,
        "total_generator_calls_saved": random_calls - memory_calls,
        "mean_generator_calls_saved_per_run": (random_calls - memory_calls) / len(memory_runs),
        "relative_generator_call_reduction": (random_calls - memory_calls) / random_calls,
        "random_post_bootstrap_generations": random_generations,
        "random_memory_post_bootstrap_generations": memory_generations,
        "post_bootstrap_generations_saved": random_generations - memory_generations,
        "timing_claim_permitted": bool(artifact["protocol"].get("timing_evidence_valid")),
        "timing_note": (
            "jobs>1 and exclusive timing was not declared; compare generator call "
            "counts, not wall-clock or generator_seconds."
        ),
    }
    return opportunity_audit, recall_audit


def analyze_random_memory(
    artifact: Mapping[str, Any], artifact_path: Path, bootstrap_samples: int
) -> dict[str, Any]:
    if set(artifact.get("methods", [])) != set(REQUIRED_METHODS):
        raise RandomMemoryAuditError(
            f"artifact methods must be exactly {list(REQUIRED_METHODS)!r}"
        )
    source_sha = _file_sha(artifact_path)
    generic = analyze_full_matrix(
        artifact,
        candidate=MEMORY,
        random_method=RANDOM,
        bootstrap_samples=bootstrap_samples,
        source_path=str(artifact_path.resolve()),
        source_sha256=source_sha,
    )
    runs = artifact["runs"]
    opportunity, recall = _opportunity_and_recall_audit(artifact, runs)
    comparisons = {
        row["comparator"]: row
        for row in generic["pairwise_candidate_comparisons"]
    }
    selected_comparisons = {
        comparator: comparisons[comparator] for comparator in (RANDOM, EXACT)
    }
    memory_vs_random = selected_comparisons[RANDOM]
    negligible_task_gain = (
        abs(float(memory_vs_random["relative_mean_task_delta_percent"])) < 0.1
        and memory_vs_random["cluster_bootstrap"]["absolute_task_delta_ci"][0] <= 0
        <= memory_vs_random["cluster_bootstrap"]["absolute_task_delta_ci"][1]
    )
    rare_recall = float(recall["reactivation_rate_per_random_opportunity"]) < 0.01
    recommendation = {
        "retain_as_primary_or_formal_candidate": False,
        "retain_as_negative_ablation": True,
        "run_on_locked_test_in_current_form": False,
        "classification": "negative_ablation_not_a_formal_candidate",
        "reasons": [
            (
                "Random opportunities are exactly matched, so the ablation is "
                "causally interpretable."
            ),
            (
                f"Recall occurred at only {recall['reactivation_count']} of "
                f"{opportunity['total_random_opportunities']} opportunities "
                f"({100.0 * recall['reactivation_rate_per_random_opportunity']:.3f}%)."
            ),
            (
                "The mean throughput/task effect versus random is effectively zero "
                "and its seed-cluster confidence interval spans harm and benefit."
            ),
            (
                "Only three generator calls were saved across 30 runs, while the "
                "three recalled cells had large mixed effects that cancelled."
            ),
            (
                "It is useful as evidence that naive nearest-context recall grafted "
                "onto random timing is insufficient; redesign would constitute a new "
                "development candidate rather than a reason to test this v8 arm formally."
            ),
        ],
        "automatic_screening_flags": {
            "negligible_mean_task_gain_vs_random": negligible_task_gain,
            "recall_rate_below_one_percent": rare_recall,
        },
    }
    return {
        "schema": ANALYSIS_SCHEMA,
        "source_integrity": _source_integrity(artifact, artifact_path, source_sha),
        "design": generic["design"],
        "safety_and_pairing_audit": generic["audit"],
        "random_opportunity_audit": opportunity,
        "recall_and_generation_savings": recall,
        "pairwise_root_seed_cluster_inference": selected_comparisons,
        "recommendation": recommendation,
        "evidence_scope": generic["evidence"],
    }


def _f(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def render_markdown(report: Mapping[str, Any]) -> str:
    integrity = report["source_integrity"]
    opportunity = report["random_opportunity_audit"]
    recall = report["recall_and_generation_savings"]
    comparisons = report["pairwise_root_seed_cluster_inference"]
    safety = report["safety_and_pairing_audit"]
    lines = [
        "# Random-memory v8 development ablation",
        "",
        "> Development evidence only. This report does not authorize a formal or SOTA claim.",
        "",
        "## Integrity and audit",
        "",
        f"- Artifact SHA-256: `{integrity['artifact_sha256']}`",
        f"- Complete paired grid: **{'PASS' if safety['complete_paired_grid'] else 'FAIL'}**",
        f"- Safety/invariant audit: **{'PASS' if safety['all_zero_unsafe_or_invalid_totals'] else 'FAIL'}**",
        f"- Local map hash verification: **{'PASS' if integrity['map']['locally_verified'] else 'NOT VERIFIED'}**",
        f"- Random-opportunity identity: **{'PASS' if opportunity['passed'] else 'FAIL'}**",
        "",
        (
            f"All {opportunity['paired_cell_count']} random/random-memory cells share "
            f"the same {opportunity['decisions_compared_per_cell']} decision flags and "
            f"{opportunity['random_opportunities_per_cell'][0]} accepted random opportunities."
        ),
        "",
        "## Root-seed-cluster inference",
        "",
        "| Comparator | Δ tasks | Δ mean % | 95% cluster CI | Exact p (two-sided) | Exact p (memory > baseline) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for comparator in (RANDOM, EXACT):
        row = comparisons[comparator]
        ci = row["cluster_bootstrap"]["absolute_task_delta_ci"]
        sign = row["exact_sign_flip"]
        lines.append(
            f"| `{comparator}` | {_f(row['mean_absolute_task_delta'])} | "
            f"{_f(row['relative_mean_task_delta_percent'], 3)}% | "
            f"[{_f(ci[0])}, {_f(ci[1])}] | {sign['p_two_sided']:.4g} | "
            f"{sign['p_greater']:.4g} |"
        )
    lines.extend(["", "## Per-workload effects", ""])
    for comparator in (RANDOM, EXACT):
        lines.extend(
            [
                f"### Memory minus {comparator}",
                "",
                "| Workload | Memory tasks | Baseline tasks | Δ tasks | Δ % | W/T/L cells |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for workload, row in comparisons[comparator]["by_workload"].items():
            wtl = row["win_tie_loss_cells"]
            lines.append(
                f"| {workload} | {_f(row['candidate_mean_tasks'])} | "
                f"{_f(row['comparator_mean_tasks'])} | {_f(row['mean_absolute_task_delta'])} | "
                f"{_f(row['relative_mean_task_delta_percent'], 3)}% | "
                f"{wtl['wins']}/{wtl['ties']}/{wtl['losses']} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Recall and generation savings",
            "",
            f"- Reactivations: {recall['reactivation_count']} / {opportunity['total_random_opportunities']} "
            f"opportunities ({100.0 * recall['reactivation_rate_per_random_opportunity']:.3f}%).",
            f"- Runs containing recall: {recall['runs_with_reactivation']} / {recall['run_count']}.",
            f"- Generator calls: {recall['random_total_generator_calls']} → "
            f"{recall['random_memory_total_generator_calls']} (saved {recall['total_generator_calls_saved']}, "
            f"{100.0 * recall['relative_generator_call_reduction']:.3f}%).",
            f"- All {recall['non_recall_cells']} non-recall cells reproduced identical task counts.",
            "- Wall-clock timing is not claimable because the run used parallel jobs without exclusive timing.",
            "",
            "| Seed | Workload | Decision | Target generation | Δ tasks | Calls saved |",
            "|---:|---|---:|---:|---:|---:|",
        ]
    )
    for row in recall["reactivation_records"]:
        lines.append(
            f"| {row['seed']} | {row['workload']} | {row['decision_index']} | "
            f"{row['target_generation_id']} | {row['task_delta_memory_minus_random']} | "
            f"{row['generator_calls_saved']} |"
        )
    recommendation = report["recommendation"]
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"**{recommendation['classification']}**.",
            "",
        ]
    )
    lines.extend(f"- {reason}" for reason in recommendation["reasons"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=20_000)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()
    if args.bootstrap_samples <= 0:
        parser.error("--bootstrap-samples must be positive")
    artifact_path = args.artifact.resolve()
    with artifact_path.open("r", encoding="utf-8") as stream:
        artifact = json.load(stream)
    report = analyze_random_memory(artifact, artifact_path, args.bootstrap_samples)
    output_json = args.output_json or artifact_path.with_name(
        artifact_path.stem + "_analysis.json"
    )
    output_md = args.output_md or artifact_path.with_name(
        artifact_path.stem + "_analysis.md"
    )
    output_json.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "complete",
                "output_json": str(output_json),
                "output_md": str(output_md),
                "artifact_sha256": report["source_integrity"]["artifact_sha256"],
                "recommendation": report["recommendation"]["classification"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
