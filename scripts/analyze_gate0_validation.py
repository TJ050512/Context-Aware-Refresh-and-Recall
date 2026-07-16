#!/usr/bin/env python3
"""Strict paired analysis for a Gate-0 publication-MVP validation artifact.

The default seed contract is the predeclared ten-seed validation split
101--110.  Results from this script are diagnostic evidence for a GO/NO-GO
decision; they are never labelled as a SOTA result.  A locked test split and
aligned external baselines remain necessary for any confirmatory claim.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


SOURCE_SCHEMA = "dai.gate0.publication-mvp/v1"
ANALYSIS_SCHEMA = "dai.gate0.validation-analysis/v1"
DEFAULT_VALIDATION_SEEDS = tuple(range(101, 111))
DEFAULT_BOOTSTRAP_SEED = 20260714
DEFAULT_BOOTSTRAP_SAMPLES = 100_000
BASELINES = ("uniform", "never")


class ArtifactValidationError(ValueError):
    """Raised when the input does not satisfy the strict pairing contract."""


def _require_plain_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArtifactValidationError(f"{field} must be a JSON integer")
    return value


def _require_nonnegative_int(value: Any, field: str) -> int:
    value = _require_plain_int(value, field)
    if value < 0:
        raise ArtifactValidationError(f"{field} must be nonnegative")
    return value


def _ordered_unique(values: Iterable[Any], field: str) -> List[Any]:
    result = list(values)
    if len(result) != len(set(result)):
        raise ArtifactValidationError(f"{field} must not contain duplicates")
    return result


def validate_artifact(
    artifact: Mapping[str, Any],
    expected_seeds: Sequence[int] = DEFAULT_VALIDATION_SEEDS,
) -> Tuple[List[int], List[str], Dict[Tuple[str, int], Mapping[str, Any]]]:
    """Validate schema, split identity, and a complete method-by-seed grid."""

    if artifact.get("schema") != SOURCE_SCHEMA:
        raise ArtifactValidationError(
            f"schema must be {SOURCE_SCHEMA!r}, got {artifact.get('schema')!r}"
        )
    if artifact.get("status") != "complete":
        raise ArtifactValidationError("source artifact status must be 'complete'")

    raw_seeds = artifact.get("seeds")
    if not isinstance(raw_seeds, list):
        raise ArtifactValidationError("seeds must be a JSON list")
    seeds = _ordered_unique(
        (_require_plain_int(seed, "seed") for seed in raw_seeds), "seeds"
    )
    expected = _ordered_unique(
        (_require_plain_int(seed, "expected seed") for seed in expected_seeds),
        "expected_seeds",
    )
    if len(expected) != 10:
        raise ArtifactValidationError(
            "strict Gate-0 validation analysis requires exactly 10 expected seeds"
        )
    if set(seeds) != set(expected) or len(seeds) != len(expected):
        raise ArtifactValidationError(
            f"validation seeds must be exactly {expected}, got {seeds}"
        )

    raw_methods = artifact.get("methods")
    if not isinstance(raw_methods, list) or not raw_methods:
        raise ArtifactValidationError("methods must be a non-empty JSON list")
    if any(not isinstance(method, str) or not method for method in raw_methods):
        raise ArtifactValidationError("every method must be a non-empty string")
    methods = _ordered_unique(raw_methods, "methods")
    missing_baselines = [name for name in BASELINES if name not in methods]
    if missing_baselines:
        raise ArtifactValidationError(
            f"strict paired analysis requires baselines {missing_baselines}"
        )

    runs = artifact.get("runs")
    if not isinstance(runs, list):
        raise ArtifactValidationError("runs must be a JSON list")
    by_key: Dict[Tuple[str, int], Mapping[str, Any]] = {}
    allowed_methods = set(methods)
    allowed_seeds = set(seeds)
    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            raise ArtifactValidationError(f"runs[{index}] must be an object")
        method = run.get("method")
        seed = run.get("seed")
        if method not in allowed_methods:
            raise ArtifactValidationError(
                f"runs[{index}].method {method!r} is not declared in methods"
            )
        seed = _require_plain_int(seed, f"runs[{index}].seed")
        if seed not in allowed_seeds:
            raise ArtifactValidationError(
                f"runs[{index}].seed {seed} is not declared in seeds"
            )
        _require_nonnegative_int(
            run.get("num_task_finished"),
            f"runs[{index}].num_task_finished",
        )
        _require_nonnegative_int(
            run.get("publication_count"),
            f"runs[{index}].publication_count",
        )
        key = (method, seed)
        if key in by_key:
            raise ArtifactValidationError(
                f"duplicate run for method={method!r}, seed={seed}"
            )
        by_key[key] = run

    expected_keys = set(itertools.product(methods, seeds))
    actual_keys = set(by_key)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        raise ArtifactValidationError(
            f"runs are not a complete paired grid; missing={missing}, extra={extra}"
        )
    return seeds, methods, by_key


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("cannot compute a percentile of an empty sequence")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(
        sorted_values[lower] * (1.0 - weight)
        + sorted_values[upper] * weight
    )


def paired_bootstrap_mean_ci(
    deltas: Sequence[int],
    *,
    samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> List[float]:
    """Percentile CI from paired (seed-level) bootstrap resampling."""

    if not deltas:
        raise ValueError("paired bootstrap requires at least one delta")
    if samples <= 0:
        raise ValueError("bootstrap samples must be positive")
    rng = random.Random(seed)
    n = len(deltas)
    means = [
        math.fsum(deltas[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(samples)
    ]
    means.sort()
    return [_percentile(means, 0.025), _percentile(means, 0.975)]


def exact_paired_sign_flip(deltas: Sequence[int]) -> Dict[str, Any]:
    """Two-sided exact paired randomization test on the mean difference.

    Zero deltas are omitted from enumeration because flipping their signs
    creates duplicate outcomes without changing the exact probability.
    At most 20 non-zero pairs are accepted, making the test exhaustive rather
    than Monte Carlo.  The null statistic is ``abs(mean paired delta)``;
    comparison by sums is equivalent because every permutation has the same n.
    """

    nonzero = [int(delta) for delta in deltas if delta != 0]
    if len(nonzero) > 20:
        raise ValueError("exact sign-flip test supports at most 20 non-zero pairs")
    if not nonzero:
        return {
            "test": "exact paired sign-flip/randomization",
            "alternative": "two-sided",
            "statistic": "absolute mean paired delta",
            "nonzero_pairs": 0,
            "extreme_assignments": 1,
            "total_assignments": 1,
            "p_value": 1.0,
        }

    observed_abs_sum = abs(sum(nonzero))
    total = 1 << len(nonzero)
    extreme = 0

    # Exhaust all assignments in Gray-code order, updating one sign per step.
    signed_sum = sum(nonzero)
    previous_gray = 0
    for assignment in range(total):
        gray = assignment ^ (assignment >> 1)
        if assignment:
            changed = gray ^ previous_gray
            index = (changed & -changed).bit_length() - 1
            if gray & changed:
                signed_sum -= 2 * nonzero[index]
            else:
                signed_sum += 2 * nonzero[index]
        if abs(signed_sum) >= observed_abs_sum:
            extreme += 1
        previous_gray = gray

    return {
        "test": "exact paired sign-flip/randomization",
        "alternative": "two-sided",
        "statistic": "absolute mean paired delta",
        "nonzero_pairs": len(nonzero),
        "extreme_assignments": extreme,
        "total_assignments": total,
        "p_value": extreme / total,
    }


def _publication_summary(
    counts_by_seed: Mapping[str, int],
) -> Dict[str, Any]:
    counts = list(counts_by_seed.values())
    return {
        "counts_by_seed": dict(counts_by_seed),
        "mean": statistics.fmean(counts),
        "median": statistics.median(counts),
        "minimum": min(counts),
        "maximum": max(counts),
        "total": sum(counts),
    }


def _paired_comparison(
    candidate_by_seed: Mapping[int, int],
    baseline_by_seed: Mapping[int, int],
    seeds: Sequence[int],
    *,
    bootstrap_samples: int,
    bootstrap_seed: int,
) -> Dict[str, Any]:
    deltas = [candidate_by_seed[seed] - baseline_by_seed[seed] for seed in seeds]
    wins = sum(delta > 0 for delta in deltas)
    ties = sum(delta == 0 for delta in deltas)
    losses = sum(delta < 0 for delta in deltas)
    return {
        "paired_deltas_by_seed": {
            str(seed): delta for seed, delta in zip(seeds, deltas)
        },
        "n_pairs": len(deltas),
        "mean_delta_num_task_finished": statistics.fmean(deltas),
        "median_delta_num_task_finished": statistics.median(deltas),
        "win_tie_loss": {"wins": wins, "ties": ties, "losses": losses},
        "paired_bootstrap_95_ci_mean_delta": paired_bootstrap_mean_ci(
            deltas, samples=bootstrap_samples, seed=bootstrap_seed
        ),
        "exact_paired_sign_flip_two_sided": exact_paired_sign_flip(deltas),
    }


def analyze_artifact(
    artifact: Mapping[str, Any],
    *,
    expected_seeds: Sequence[int] = DEFAULT_VALIDATION_SEEDS,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    source_path: str = "<in-memory>",
    source_sha256: str = "",
) -> Dict[str, Any]:
    seeds, methods, by_key = validate_artifact(artifact, expected_seeds)
    task_counts: Dict[str, Dict[int, int]] = {}
    for method in methods:
        task_counts[method] = {
            seed: int(by_key[(method, seed)]["num_task_finished"])
            for seed in seeds
        }

    method_results: Dict[str, Any] = {}
    for method in methods:
        publication_by_seed = {
            str(seed): int(by_key[(method, seed)]["publication_count"])
            for seed in seeds
        }
        method_results[method] = {
            "num_task_finished_by_seed": {
                str(seed): task_counts[method][seed] for seed in seeds
            },
            "mean_num_task_finished": statistics.fmean(
                task_counts[method].values()
            ),
            "median_num_task_finished": statistics.median(
                task_counts[method].values()
            ),
            "publication_counts": _publication_summary(publication_by_seed),
            "comparisons": {
                baseline: _paired_comparison(
                    task_counts[method],
                    task_counts[baseline],
                    seeds,
                    bootstrap_samples=bootstrap_samples,
                    bootstrap_seed=bootstrap_seed,
                )
                for baseline in BASELINES
            },
        }

    return {
        "schema": ANALYSIS_SCHEMA,
        "status": "complete",
        "source": {"path": source_path, "sha256": source_sha256},
        "analysis_scope": {
            "split": "validation",
            "seeds": seeds,
            "num_seeds": len(seeds),
            "evidence_class": "diagnostic",
            "sota_claim_permitted": False,
            "confirmatory_claim_permitted": False,
            "interpretation": (
                "GO/NO-GO and method-selection evidence only; ten validation "
                "seeds are not a SOTA result. Any SOTA claim requires the "
                "predeclared locked test split and aligned public baselines."
            ),
        },
        "bootstrap": {
            "unit": "paired seed",
            "statistic": "mean paired delta in num_task_finished",
            "method": "percentile",
            "samples": bootstrap_samples,
            "seed": bootstrap_seed,
            "confidence_level": 0.95,
        },
        "randomization_test": {
            "unit": "paired seed",
            "method": "exhaustive sign flips over non-zero deltas",
            "alternative": "two-sided",
            "maximum_nonzero_pairs": 20,
            "multiplicity_adjusted": False,
            "interpretation": (
                "Exploratory diagnostic p-values; do not treat them as "
                "confirmatory evidence or a SOTA claim."
            ),
        },
        "methods": method_results,
    }


def _print_summary(analysis: Mapping[str, Any]) -> None:
    scope = analysis["analysis_scope"]
    print(
        "VALIDATION ONLY: diagnostic/no-SOTA "
        f"({scope['num_seeds']} seeds: {scope['seeds']})"
    )
    print(
        "method\tbaseline\tmean_delta\tmedian_delta\tW/T/L\tCI95\texact_p"
    )
    for method, result in analysis["methods"].items():
        for baseline in BASELINES:
            comparison = result["comparisons"][baseline]
            wtl = comparison["win_tie_loss"]
            ci = comparison["paired_bootstrap_95_ci_mean_delta"]
            p_value = comparison["exact_paired_sign_flip_two_sided"]["p_value"]
            print(
                f"{method}\t{baseline}\t"
                f"{comparison['mean_delta_num_task_finished']:.6g}\t"
                f"{comparison['median_delta_num_task_finished']:.6g}\t"
                f"{wtl['wins']}/{wtl['ties']}/{wtl['losses']}\t"
                f"[{ci[0]:.6g}, {ci[1]:.6g}]\t{p_value:.8g}"
            )
        publications = result["publication_counts"]
        print(
            f"  publications[{method}]: mean={publications['mean']:.6g}, "
            f"median={publications['median']:.6g}, total={publications['total']}, "
            f"range=[{publications['minimum']}, {publications['maximum']}]"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Gate-0 publication-MVP JSON")
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "analysis JSON (default: <input-stem>.validation-analysis.json)"
        ),
    )
    parser.add_argument(
        "--expected-seeds",
        type=int,
        nargs="+",
        default=list(DEFAULT_VALIDATION_SEEDS),
        help="strict validation split identity (default: 101 ... 110)",
    )
    parser.add_argument(
        "--bootstrap-samples",
        type=int,
        default=DEFAULT_BOOTSTRAP_SAMPLES,
    )
    parser.add_argument(
        "--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.bootstrap_samples <= 0:
        raise SystemExit("--bootstrap-samples must be positive")
    raw = args.input.read_bytes()
    try:
        artifact = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {args.input}: {exc}") from exc
    if not isinstance(artifact, dict):
        raise SystemExit("input JSON root must be an object")
    output = args.output
    if output is None:
        output = args.input.with_name(
            args.input.stem + ".validation-analysis.json"
        )
    try:
        analysis = analyze_artifact(
            artifact,
            expected_seeds=args.expected_seeds,
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_seed=args.bootstrap_seed,
            source_path=str(args.input.resolve()),
            source_sha256=hashlib.sha256(raw).hexdigest(),
        )
    except (ArtifactValidationError, ValueError) as exc:
        raise SystemExit(f"analysis refused: {exc}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(analysis, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _print_summary(analysis)
    print(f"analysis={output}")


if __name__ == "__main__":
    main()
