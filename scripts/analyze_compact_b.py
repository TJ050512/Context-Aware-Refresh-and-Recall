#!/usr/bin/env python3
"""Reproduce the reported Experiment B statistics from the compact CSV only.

This reviewer-facing analyzer uses only Python's standard library.  It does
not inspect raw traces, machine attestations, absolute paths, or the historical
freeze control plane.  The raw archive remains the authority for the deeper
execution and integrity audit; this script independently reproduces the
reported numerical conclusions from the anonymous 3,840-row run table.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import defaultdict
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
import struct
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT / "results" / "same_call_confirmation_b" / "compact_runs.csv"
)
DEFAULT_OUTPUT = ROOT / "reports" / "compact_b_analysis.json"

ROOT_SEEDS = (
    880565, 534821, 257578, 500976, 294860, 954705, 190142, 429853,
    398397, 560584, 175381, 598292, 461566, 526869, 115950, 130998,
    655067, 585455, 362413, 552654, 664860, 253714, 962860, 907962,
    381214, 583444, 371204, 934561, 491276, 541256, 523055, 713041,
    537643, 699809, 204011, 330180, 113743, 257704, 152753, 657283,
)
METHODS = (
    "bootstrap_only",
    "exact_even_G4",
    "exact_even_G5",
    "random_G5",
    "js_cap_G5",
    "context_no_reactivation_B25",
    "context_memory_B25",
    "exact_even_B25",
)
WORKLOADS = ("stationary", "abrupt", "recurrent")
SCENARIOS = {
    "narrow_r020": {
        "map_id": "warehouse_small_narrow_kiva",
        "map_sha256": "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
        "agents": 218,
    },
    "narrow_r035": {
        "map_id": "warehouse_small_narrow_kiva",
        "map_sha256": "866e664553959fb44af359276885e2e72192eaf36fd0f4abde3726474703cbb6",
        "agents": 382,
    },
    "regular_r020": {
        "map_id": "warehouse_small_kiva",
        "map_sha256": "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
        "agents": 255,
    },
    "regular_r035": {
        "map_id": "warehouse_small_kiva",
        "map_sha256": "0e597b0c8ec25414d96bf2080ff5a60bbd3bb8f33f3622965807b7746f8a27dd",
        "agents": 447,
    },
}

FIELDS = (
    "scenario",
    "map_id",
    "map_sha256",
    "agents",
    "root_seed",
    "workload",
    "method",
    "num_task_finished",
    "throughput_per_timestep",
    "generator_calls",
    "post_bootstrap_generation_count",
    "post_bootstrap_reactivation_count",
    "post_bootstrap_publication_count",
    "effective_guidance_switch_count",
    "safety_passed",
    "invariants_passed",
    "task_tape_manifest_sha256",
    "release_projection_fingerprint",
    "reset_causal_fingerprint",
    "pairing_fingerprint",
)

FOCAL = "context_memory_B25"
DENSE = "exact_even_B25"
SUPERIORITY_COMPARATORS = (
    "bootstrap_only",
    "exact_even_G4",
    "exact_even_G5",
    "random_G5",
    "js_cap_G5",
    "context_no_reactivation_B25",
)
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_715
NI_MARGIN = 0.01
SIGN_FLIP_TOLERANCE = 1e-15
EXACT_ENUMERATION_MAX_ROOTS = 20


class CompactAnalysisError(ValueError):
    """The compact table is not the complete frozen Experiment B matrix."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256(value: str, field: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise CompactAnalysisError(f"{field} must be a lowercase SHA-256")
    return value


def _integer(value: str, field: str, *, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise CompactAnalysisError(f"{field} must be an integer") from error
    if str(parsed) != value or parsed < minimum:
        raise CompactAnalysisError(f"{field} must be a canonical integer >= {minimum}")
    return parsed


def _float(value: str, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise CompactAnalysisError(f"{field} must be numeric") from error
    if not math.isfinite(parsed):
        raise CompactAnalysisError(f"{field} must be finite")
    return parsed


def _boolean(value: str, field: str) -> bool:
    if value not in {"true", "false"}:
        raise CompactAnalysisError(f"{field} must be true or false")
    return value == "true"


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    if not materialized:
        raise CompactAnalysisError("mean requires at least one value")
    return math.fsum(materialized) / len(materialized)


def _percentile(values: Sequence[float], probability: float) -> float:
    if not values or not 0.0 <= probability <= 1.0:
        raise CompactAnalysisError("invalid percentile request")
    ordered = sorted(float(value) for value in values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def load_compact(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load and fully audit the path-free compact Experiment B matrix."""

    resolved = path.expanduser().resolve()
    try:
        with resolved.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise CompactAnalysisError("compact CSV header differs from the v1 schema")
            raw_rows = list(reader)
    except OSError as error:
        raise CompactAnalysisError(f"cannot read compact CSV: {error}") from error
    if len(raw_rows) != 3840:
        raise CompactAnalysisError("compact CSV must contain exactly 3,840 data rows")

    rows: list[dict[str, Any]] = []
    identities: set[tuple[str, int, str, str]] = set()
    pairing: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    for line_number, raw in enumerate(raw_rows, 2):
        if any("/" in value or "\\" in value or "@" in value for value in raw.values()):
            raise CompactAnalysisError(
                f"compact CSV contains path/account-like data on line {line_number}"
            )
        scenario = raw["scenario"]
        workload = raw["workload"]
        method = raw["method"]
        if scenario not in SCENARIOS or workload not in WORKLOADS or method not in METHODS:
            raise CompactAnalysisError(f"unknown matrix label on line {line_number}")
        expected = SCENARIOS[scenario]
        agents = _integer(raw["agents"], "agents", minimum=1)
        root_seed = _integer(raw["root_seed"], "root_seed")
        tasks = _integer(raw["num_task_finished"], "num_task_finished")
        throughput = _float(raw["throughput_per_timestep"], "throughput_per_timestep")
        calls = _integer(raw["generator_calls"], "generator_calls")
        generations = _integer(
            raw["post_bootstrap_generation_count"],
            "post_bootstrap_generation_count",
        )
        reactivations = _integer(
            raw["post_bootstrap_reactivation_count"],
            "post_bootstrap_reactivation_count",
        )
        publications = _integer(
            raw["post_bootstrap_publication_count"],
            "post_bootstrap_publication_count",
        )
        switches = _integer(
            raw["effective_guidance_switch_count"],
            "effective_guidance_switch_count",
        )
        safety_passed = _boolean(raw["safety_passed"], "safety_passed")
        invariants_passed = _boolean(raw["invariants_passed"], "invariants_passed")
        if (
            raw["map_id"] != expected["map_id"]
            or raw["map_sha256"] != expected["map_sha256"]
            or agents != expected["agents"]
        ):
            raise CompactAnalysisError(f"scenario identity mismatch on line {line_number}")
        if root_seed not in ROOT_SEEDS:
            raise CompactAnalysisError(f"unknown B root on line {line_number}")
        if throughput != tasks / 2000.0:
            raise CompactAnalysisError(f"throughput/tasks mismatch on line {line_number}")
        if calls != 1 + generations:
            raise CompactAnalysisError(f"generator-call conservation failed on line {line_number}")
        if generations + reactivations != publications or switches != publications:
            raise CompactAnalysisError(f"publication partition failed on line {line_number}")

        tape_sha = _sha256(raw["task_tape_manifest_sha256"], "task tape hash")
        release_sha = _sha256(raw["release_projection_fingerprint"], "release hash")
        reset_sha = _sha256(raw["reset_causal_fingerprint"], "reset hash")
        pair_sha = _sha256(raw["pairing_fingerprint"], "pairing hash")
        expected_pair = hashlib.sha256(
            json.dumps(
                {
                    "task_tape_manifest_sha256": tape_sha,
                    "release_projection_fingerprint": release_sha,
                    "reset_causal_fingerprint": reset_sha,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        if pair_sha != expected_pair:
            raise CompactAnalysisError(f"pairing hash is invalid on line {line_number}")

        identity = (scenario, root_seed, workload, method)
        if identity in identities:
            raise CompactAnalysisError(f"duplicate matrix cell on line {line_number}")
        identities.add(identity)
        pairing[(scenario, root_seed, workload)].add(pair_sha)
        rows.append(
            {
                "scenario_id": scenario,
                "map_id": raw["map_id"],
                "map_sha256": raw["map_sha256"],
                "agents": agents,
                "root_seed": root_seed,
                "workload": workload,
                "method": method,
                "num_task_finished": tasks,
                "throughput_per_timestep": throughput,
                "generator_calls": calls,
                "post_bootstrap_generation_count": generations,
                "post_bootstrap_reactivation_count": reactivations,
                "post_bootstrap_publication_count": publications,
                "effective_guidance_switch_count": switches,
                "safety_passed": safety_passed,
                "invariants_passed": invariants_passed,
                "pairing_fingerprint": pair_sha,
            }
        )

    expected_identities = set(
        itertools.product(SCENARIOS, ROOT_SEEDS, WORKLOADS, METHODS)
    )
    if identities != expected_identities:
        raise CompactAnalysisError("compact CSV does not cover the frozen B matrix")
    if any(len(fingerprints) != 1 for fingerprints in pairing.values()):
        raise CompactAnalysisError("paired methods differ in exogenous-input fingerprint")
    if not all(row["safety_passed"] and row["invariants_passed"] for row in rows):
        raise CompactAnalysisError("compact CSV contains a safety/invariant failure")

    audit = {
        "passed": True,
        "row_count": len(rows),
        "unique_cells": len(identities),
        "paired_groups": len(pairing),
        "complete_3840_run_matrix": True,
        "all_safety_and_invariants_pass": True,
        "pairing_fingerprints_match_within_all_480_groups": True,
        "path_and_account_fields_absent": True,
        "generator_and_publication_conservation_pass": True,
    }
    return rows, audit


def _root_bootstrap(
    root_relative: Sequence[float], root_absolute: Sequence[float]
) -> dict[str, Any]:
    rng = random.Random(BOOTSTRAP_SEED)
    relative_draws: list[float] = []
    absolute_draws: list[float] = []
    n = len(root_relative)
    for _ in range(BOOTSTRAP_SAMPLES):
        indices = [rng.randrange(n) for _ in range(n)]
        relative_draws.append(_mean(root_relative[index] for index in indices))
        absolute_draws.append(_mean(root_absolute[index] for index in indices))
    return {
        "method": "whole_root_percentile_bootstrap",
        "independent_unit": "root_seed",
        "samples": BOOTSTRAP_SAMPLES,
        "rng_seed": BOOTSTRAP_SEED,
        "confidence_level": 0.95,
        "mean_relative_effect_ci": [
            _percentile(relative_draws, 0.025),
            _percentile(relative_draws, 0.975),
        ],
        "mean_absolute_task_delta_ci": [
            _percentile(absolute_draws, 0.025),
            _percentile(absolute_draws, 0.975),
        ],
    }


def _binary_integer(value: float) -> tuple[int, int]:
    numerator, denominator = float(value).as_integer_ratio()
    exponent = denominator.bit_length() - 1
    if denominator != 1 << exponent:
        raise AssertionError("binary64 denominator is not a power of two")
    return numerator, exponent


def _signed_sums(weights: Sequence[int]) -> list[int]:
    sums = [0]
    for weight in weights:
        prior = sums
        sums = [value - weight for value in prior]
        sums.extend(value + weight for value in prior)
    return sums


def _threshold_midpoint(
    values: Sequence[float], threshold: float
) -> tuple[list[int], int, bool]:
    value_parts = [_binary_integer(value) for value in values]
    previous = math.nextafter(threshold, -math.inf)
    threshold_part = _binary_integer(threshold)
    previous_part = _binary_integer(previous)
    midpoint_base_exponent = max(threshold_part[1], previous_part[1])
    midpoint_numerator = (
        previous_part[0] << (midpoint_base_exponent - previous_part[1])
    ) + (threshold_part[0] << (midpoint_base_exponent - threshold_part[1]))
    midpoint_exponent = midpoint_base_exponent + 1
    common_exponent = max(
        midpoint_exponent, *(exponent for _, exponent in value_parts)
    )
    weights = [
        numerator << (common_exponent - exponent)
        for numerator, exponent in value_parts
    ]
    midpoint = midpoint_numerator << (common_exponent - midpoint_exponent)
    raw_bits = struct.unpack(">Q", struct.pack(">d", threshold))[0]
    return weights, midpoint, (raw_bits & 1) == 0


def _exact_sign_flip_enumerated(root_effects: Sequence[float]) -> dict[str, Any]:
    nonzero = [float(value) for value in root_effects if value != 0.0]
    observed = math.fsum(nonzero)
    assignments = 1 << len(nonzero)
    if not nonzero:
        return {
            "method": "exact_root_seed_sign_flip",
            "alternative": "greater",
            "nonzero_root_seeds": 0,
            "ties_omitted": len(root_effects),
            "assignments": 1,
            "p_greater": 1.0,
        }
    extreme = 0
    for bits in range(assignments):
        statistic = math.fsum(
            value if bits & (1 << index) else -value
            for index, value in enumerate(nonzero)
        )
        extreme += statistic >= observed - SIGN_FLIP_TOLERANCE
    return {
        "method": "exact_root_seed_sign_flip",
        "alternative": "greater",
        "nonzero_root_seeds": len(nonzero),
        "ties_omitted": len(root_effects) - len(nonzero),
        "assignments": assignments,
        "p_greater": extreme / assignments,
    }


def _exact_sign_flip_mitm(root_effects: Sequence[float]) -> dict[str, Any]:
    nonzero = [float(value) for value in root_effects if value != 0.0]
    assignments = 1 << len(nonzero)
    if not nonzero:
        return {
            "method": "exact_root_seed_sign_flip",
            "alternative": "greater",
            "nonzero_root_seeds": 0,
            "ties_omitted": len(root_effects),
            "assignments": 1,
            "p_greater": 1.0,
        }
    threshold = math.fsum(nonzero) - SIGN_FLIP_TOLERANCE
    if not math.isfinite(threshold):
        raise CompactAnalysisError("sign-flip statistic must remain finite")
    weights, boundary, inclusive = _threshold_midpoint(nonzero, threshold)
    split = len(weights) // 2
    left = _signed_sums(weights[:split])
    right = _signed_sums(weights[split:])
    right.sort()
    if inclusive:
        extreme = sum(
            len(right) - bisect_left(right, boundary - partial)
            for partial in left
        )
    else:
        extreme = sum(
            len(right) - bisect_right(right, boundary - partial)
            for partial in left
        )
    return {
        "method": "exact_root_seed_sign_flip",
        "alternative": "greater",
        "nonzero_root_seeds": len(nonzero),
        "ties_omitted": len(root_effects) - len(nonzero),
        "assignments": assignments,
        "p_greater": extreme / assignments,
    }


def exact_sign_flip(root_effects: Sequence[float]) -> dict[str, Any]:
    nonzero = sum(float(value) != 0.0 for value in root_effects)
    if nonzero <= EXACT_ENUMERATION_MAX_ROOTS:
        return _exact_sign_flip_enumerated(root_effects)
    return _exact_sign_flip_mitm(root_effects)


def _comparison(
    candidate: str,
    comparator: str,
    indexed: Mapping[tuple[str, str, int, str], Mapping[str, Any]],
    *,
    include_unshifted_sign_flip: bool = True,
) -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    by_root_relative: dict[int, list[float]] = defaultdict(list)
    by_root_absolute: dict[int, list[float]] = defaultdict(list)
    for scenario, root_seed, workload in itertools.product(
        SCENARIOS, ROOT_SEEDS, WORKLOADS
    ):
        left = indexed[(scenario, candidate, root_seed, workload)]
        right = indexed[(scenario, comparator, root_seed, workload)]
        candidate_tasks = float(left["num_task_finished"])
        comparator_tasks = float(right["num_task_finished"])
        if comparator_tasks <= 0.0:
            raise CompactAnalysisError("relative-effect comparator completed no tasks")
        relative = (candidate_tasks - comparator_tasks) / comparator_tasks
        absolute = candidate_tasks - comparator_tasks
        cells.append(
            {
                "scenario_id": scenario,
                "map_group": "narrow" if scenario.startswith("narrow_") else "regular",
                "root_seed": root_seed,
                "workload": workload,
                "relative_effect": relative,
                "absolute_task_delta": absolute,
            }
        )
        by_root_relative[root_seed].append(relative)
        by_root_absolute[root_seed].append(absolute)
    root_relative = [_mean(by_root_relative[root]) for root in ROOT_SEEDS]
    root_absolute = [_mean(by_root_absolute[root]) for root in ROOT_SEEDS]

    def direction(field: str, value: str) -> dict[str, Any]:
        selected = [cell for cell in cells if cell[field] == value]
        return {
            "n_cells": len(selected),
            "mean_relative_effect": _mean(
                float(cell["relative_effect"]) for cell in selected
            ),
            "mean_absolute_task_delta": _mean(
                float(cell["absolute_task_delta"]) for cell in selected
            ),
        }

    result: dict[str, Any] = {
        "candidate": candidate,
        "comparator": comparator,
        "independent_unit": "root_seed",
        "n_root_seed_clusters": 40,
        "n_paired_cells": 480,
        "root_relative_effects": [
            {
                "root_seed": root,
                "relative_effect": effect,
                "absolute_task_delta": root_absolute[index],
            }
            for index, (root, effect) in enumerate(zip(ROOT_SEEDS, root_relative))
        ],
        "mean_relative_effect": _mean(root_relative),
        "mean_relative_effect_percent": 100.0 * _mean(root_relative),
        "median_root_relative_effect": statistics.median(root_relative),
        "mean_absolute_task_delta": _mean(root_absolute),
        "root_win_tie_loss": {
            "wins": sum(value > 0.0 for value in root_relative),
            "ties": sum(value == 0.0 for value in root_relative),
            "losses": sum(value < 0.0 for value in root_relative),
        },
        "cluster_bootstrap": _root_bootstrap(root_relative, root_absolute),
        "map_effects": {
            name: direction("map_group", name) for name in ("narrow", "regular")
        },
        "workload_effects": {
            name: direction("workload", name) for name in WORKLOADS
        },
        "scenario_effects": {
            name: direction("scenario_id", name) for name in SCENARIOS
        },
    }
    if include_unshifted_sign_flip:
        result["exact_sign_flip"] = exact_sign_flip(root_relative)
    return result


def _holm_adjust(comparisons: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    raw = {
        comparator: float(comparisons[comparator]["exact_sign_flip"]["p_greater"])
        for comparator in SUPERIORITY_COMPARATORS
    }
    ordered = sorted(raw, key=lambda name: (raw[name], name))
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for rank, comparator in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * raw[comparator]))
        adjusted[comparator] = running
    for comparator, value in adjusted.items():
        comparisons[comparator]["exact_sign_flip"]["p_greater_holm"] = value
    return {
        "method": "Holm step-down",
        "familywise_alpha": 0.05,
        "family_size": 6,
        "ordered_comparators": ordered,
        "raw_p_greater": raw,
        "adjusted_p_greater": adjusted,
    }


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    return {
        "mean": _mean(values),
        "median": statistics.median(values),
        "p90": _percentile(values, 0.90),
        "maximum": max(values),
        "minimum": min(values),
    }


def _method_summaries(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for method in METHODS:
        selected = [row for row in rows if row["method"] == method]
        tasks = [float(row["num_task_finished"]) for row in selected]
        throughput = [float(row["throughput_per_timestep"]) for row in selected]
        calls = [float(row["generator_calls"]) for row in selected]
        generations = [
            float(row["post_bootstrap_generation_count"]) for row in selected
        ]
        reactivations = [
            float(row["post_bootstrap_reactivation_count"]) for row in selected
        ]
        publications = [
            float(row["post_bootstrap_publication_count"]) for row in selected
        ]
        switches = [
            float(row["effective_guidance_switch_count"]) for row in selected
        ]
        summaries[method] = {
            "n_runs": len(selected),
            "tasks": _distribution(tasks),
            "throughput_per_timestep": _distribution(throughput),
            "total_generator_calls": {
                **_distribution(calls),
                "fraction_at_most_5": sum(value <= 5.0 for value in calls) / len(calls),
                "fraction_at_most_6": sum(value <= 6.0 for value in calls) / len(calls),
            },
            "post_bootstrap_generations": _distribution(generations),
            "reactivations": _distribution(reactivations),
            "post_bootstrap_publications": _distribution(publications),
            "effective_switches": _distribution(switches),
        }
    return summaries


def _pareto(summaries: Mapping[str, Any]) -> dict[str, Any]:
    points = {
        method: {
            "mean_tasks": float(summaries[method]["tasks"]["mean"]),
            "mean_total_generator_calls": float(
                summaries[method]["total_generator_calls"]["mean"]
            ),
        }
        for method in METHODS
    }
    dominators: dict[str, list[str]] = {method: [] for method in METHODS}
    for candidate, target in itertools.permutations(METHODS, 2):
        left = points[candidate]
        right = points[target]
        if (
            left["mean_tasks"] >= right["mean_tasks"]
            and left["mean_total_generator_calls"]
            <= right["mean_total_generator_calls"]
            and (
                left["mean_tasks"] > right["mean_tasks"]
                or left["mean_total_generator_calls"]
                < right["mean_total_generator_calls"]
            )
        ):
            dominators[target].append(candidate)
    return {
        "definition": "no fewer mean tasks and no more mean calls, with at least one strict",
        "points": points,
        "dominators": dominators,
        "frontier_methods": [method for method in METHODS if not dominators[method]],
        "focal_not_point_dominated": not dominators[FOCAL],
    }


def analyze(rows: Sequence[Mapping[str, Any]], audit: Mapping[str, Any], source_sha256: str) -> dict[str, Any]:
    indexed = {
        (
            str(row["scenario_id"]),
            str(row["method"]),
            int(row["root_seed"]),
            str(row["workload"]),
        ): row
        for row in rows
    }
    superiority = {
        comparator: _comparison(FOCAL, comparator, indexed)
        for comparator in SUPERIORITY_COMPARATORS
    }
    multiplicity = _holm_adjust(superiority)
    primary_comparison = _comparison(
        FOCAL, DENSE, indexed, include_unshifted_sign_flip=False
    )
    shifted = [
        float(row["relative_effect"]) + NI_MARGIN
        for row in primary_comparison["root_relative_effects"]
    ]
    shifted_test = exact_sign_flip(shifted)
    checks = {
        "mean_at_least_minus_0_5pct": primary_comparison["mean_relative_effect"] >= -0.005,
        "ci_lower_strictly_above_minus_1pct": primary_comparison["cluster_bootstrap"]["mean_relative_effect_ci"][0] > -0.01,
        "shifted_one_sided_p_below_0_05": shifted_test["p_greater"] < 0.05,
    }
    noninferiority = {
        "candidate": FOCAL,
        "comparator": DENSE,
        "relative_margin": -NI_MARGIN,
        "comparison": primary_comparison,
        "shifted_exact_sign_flip": shifted_test,
        "checks": checks,
        "passed": all(checks.values()),
    }
    summaries = _method_summaries(rows)
    pareto = _pareto(summaries)
    return {
        "schema": "dai.compact-same-call-confirmation-analysis/b-v1",
        "evidence_scope": (
            "anonymous compact numerical reproduction of Experiment B; "
            "raw archive required for trace-level integrity audit"
        ),
        "source": {
            "schema": "dai.compact-same-call-confirmation-runs/b-v1",
            "sha256": source_sha256,
            "row_count": 3840,
            "contains_paths_or_host_identifiers": False,
        },
        "design": {
            "methods": list(METHODS),
            "root_seeds": list(ROOT_SEEDS),
            "scenarios": list(SCENARIOS),
            "workloads": list(WORKLOADS),
            "total_runs": 3840,
            "paired_cells_per_method": 480,
            "cells_per_root_method": 12,
            "independent_unit": "root_seed",
            "bootstrap_samples": BOOTSTRAP_SAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
        },
        "audit": dict(audit),
        "method_summaries": summaries,
        "superiority_comparisons": superiority,
        "multiplicity": multiplicity,
        "noninferiority_vs_exact_even_B25": noninferiority,
        "pareto": pareto,
    }


def analyze_file(path: Path) -> dict[str, Any]:
    rows, audit = load_compact(path)
    return analyze(rows, audit, _sha256_file(path.expanduser().resolve()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and not args.force:
        raise SystemExit(f"ERROR: refusing to overwrite existing analysis: {output}")
    try:
        report = analyze_file(args.input)
    except (OSError, CompactAnalysisError) as error:
        raise SystemExit(f"ERROR: {error}") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "audit_passed": report["audit"]["passed"],
                "primary_noninferiority_passed": report[
                    "noninferiority_vs_exact_even_B25"
                ]["passed"],
                "output_sha256": _sha256_file(output),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
