#!/usr/bin/env python3
"""Verify the compact exploratory summaries shipped with the artifact.

The checks intentionally use only Python's standard library.  They recompute
the statistics that can be recovered from the published development CSVs and
validate the scope, seeds, and headline values of compact diagnostic reports.
They do not turn any exploratory analysis into confirmatory evidence.
"""

from __future__ import annotations

import csv
import glob
import hashlib
import json
import os
from pathlib import Path
from statistics import fmean, median


REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = REPO_ROOT / "carr_rl_lite_exp"
RESULT_ROOT = ARTIFACT_ROOT / "results"
SUMMARY_ROOT = RESULT_ROOT / "carr_rl_lite"
TOLERANCE = 1e-10
MICROBENCH_CSV = SUMMARY_ROOT / "microbench_narrow_r020.csv"
MICROBENCH_RAW = SUMMARY_ROOT / "microbench_narrow_r020.json"
MICROBENCH_SUMMARY = SUMMARY_ROOT / "microbench_summary.json"
MICROBENCH_NOTE = ARTIFACT_ROOT / "CONTROLLED_RESOURCE_MEASUREMENT.md"


def close(actual: float, expected: float, *, label: str) -> None:
    if abs(actual - expected) > TOLERANCE:
        raise AssertionError(f"{label}: {actual!r} != {expected!r}")


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def load_csv_group(pattern: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    paths = sorted(glob.glob(str(RESULT_ROOT / pattern)))
    if not paths:
        raise AssertionError(f"no CSV files matched {pattern}")
    for raw_path in paths:
        path = Path(raw_path)
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row["scenario"] = path.stem
                rows.append(row)
    return rows


def root_effects(
    rows: list[dict[str, str]], focal: str, comparator: str
) -> list[float]:
    methods = {row["method"] for row in rows}
    if focal not in methods or comparator not in methods:
        raise AssertionError(f"missing methods: {focal}, {comparator}")
    roots = sorted({int(row["seed"]) for row in rows})
    scenarios = sorted({row["scenario"] for row in rows})
    workloads = sorted({row["workload"] for row in rows})
    keyed = {
        (row["scenario"], int(row["seed"]), row["workload"], row["method"]): row
        for row in rows
    }
    effects = []
    for root in roots:
        cell_effects = []
        for scenario in scenarios:
            for workload in workloads:
                left = float(
                    keyed[(scenario, root, workload, focal)]["num_task_finished"]
                )
                right = float(
                    keyed[(scenario, root, workload, comparator)]["num_task_finished"]
                )
                cell_effects.append(100.0 * (left - right) / right)
        effects.append(fmean(cell_effects))
    return effects


def verify_g5cap() -> None:
    rows = load_csv_group("path_f_g5cap_dev/*.csv")
    summary = load_json(SUMMARY_ROOT / "expF_g5cap.json")
    effects = root_effects(rows, "context_memory_G5Cap", "exact_even_G5")
    if len(rows) != 480 or int(summary["n"]) != 120:
        raise AssertionError("G5Cap matrix/cell count mismatch")
    close(fmean(effects), float(summary["g5cap_vs_g5"][0]), label="G5Cap effect")
    if sum(effect > 0.0 for effect in effects) != 7:
        raise AssertionError("G5Cap positive-root count is not 7/10")
    keyed = {
        (row["scenario"], row["seed"], row["workload"], row["method"]): row
        for row in rows
    }
    wins = ties = losses = 0
    for scenario, seed, workload, method in keyed:
        if method != "context_memory_G5Cap":
            continue
        focal = float(keyed[(scenario, seed, workload, method)]["num_task_finished"])
        comp = float(
            keyed[(scenario, seed, workload, "exact_even_G5")]["num_task_finished"]
        )
        wins += focal > comp
        ties += focal == comp
        losses += focal < comp
    if [wins, ties, losses] != list(summary["wtl"]):
        raise AssertionError("G5Cap cell win/tie/loss mismatch")
    if summary["g5cap_calls"] != 5 or summary["g5_calls"] != 6:
        raise AssertionError("G5Cap generation-ceiling contract mismatch")


def verify_threshold_sensitivity() -> None:
    summary = load_json(SUMMARY_ROOT / "expG_threshsens.json")
    recomputed: dict[str, float] = {}
    for path in sorted((RESULT_ROOT / "path_g_threshold_sweep").glob("*.csv")):
        rows = load_csv_group(f"path_g_threshold_sweep/{path.name}")
        effects = root_effects(rows, "context_memory_B25", "exact_even_B25")
        recomputed[path.stem] = fmean(effects)
    if set(recomputed) != set(summary["per_variant"]):
        raise AssertionError("threshold-variant set mismatch")
    for variant, effect in recomputed.items():
        close(effect, float(summary["per_variant"][variant]), label=f"threshold {variant}")
    base = recomputed["base"]
    close(base, float(summary["base_effect"]), label="threshold base")
    maximum = max(abs(value - base) for value in recomputed.values())
    close(maximum, float(summary["max_abs_change_pp"]), label="threshold maximum")


def verify_learned_holdout() -> None:
    rows = load_csv_group("carr_rl_lite/ab_holdout/*_r0*.csv")
    summary = load_json(SUMMARY_ROOT / "ab_holdout" / "report.json")
    if len(rows) != 216 or int(summary["n_cells"]) != 72:
        raise AssertionError("learned holdout matrix/cell count mismatch")
    effects = root_effects(rows, "context_learned_lite", "context_memory_B25")
    close(fmean(effects), float(summary["learned_vs_rule"][0]), label="learned effect")
    if sum(effect < 0.0 for effect in effects) != 4:
        raise AssertionError("learned negative-root count is not 4/6")
    # Preserve and verify the historical report's original accounting.  Its
    # mean_calls_* labels were computed from effective publication events.
    # A separate raw projection below verifies true generator invocations.
    for method, key in (
        ("context_learned_lite", "mean_calls_learned"),
        ("context_memory_B25", "mean_calls_rule"),
    ):
        publications = fmean(
            float(row["post_bootstrap_publication_count"])
            for row in rows
            if row["method"] == method
        )
        close(publications, float(summary[key]), label=f"legacy {key}")

    resource_csv = SUMMARY_ROOT / "ab_holdout" / "resource_counts.csv"
    with resource_csv.open(newline="", encoding="utf-8") as handle:
        resource_rows = list(csv.DictReader(handle))
    resource_summary = load_json(
        SUMMARY_ROOT / "ab_holdout" / "resource_counts_summary.json"
    )
    if len(resource_rows) != 216 or int(resource_summary["rows"]) != 216:
        raise AssertionError("holdout resource-count row mismatch")
    for method, expected in resource_summary["methods"].items():
        selected = [row for row in resource_rows if row["method"] == method]
        if len(selected) != 72:
            raise AssertionError(f"resource-count cell mismatch for {method}")
        for column, key in (
            ("total_generator_calls", "mean_total_generator_calls"),
            ("post_bootstrap_generation_count", "mean_post_bootstrap_generations"),
            ("post_bootstrap_reactivation_count", "mean_post_bootstrap_recalls"),
            ("post_bootstrap_publication_count", "mean_post_bootstrap_publications"),
        ):
            actual = fmean(float(row[column]) for row in selected)
            close(actual, float(expected[key]), label=f"{method} {column}")


def verify_compact_diagnostics() -> None:
    model = load_json(SUMMARY_ROOT / "model" / "report.json")
    if int(model["n_decision_rows"]) != 23_760 or int(model["n_seeds"]) != 10:
        raise AssertionError("model-report sample size mismatch")
    close(float(model["raw4"]["cv_auc_mean"]), 0.519271784580151, label="raw4 AUC")
    close(
        float(model["fullstate"]["cv_agreement_mean"]),
        0.9822390572390572,
        label="full-state agreement",
    )

    latency = load_json(SUMMARY_ROOT / "expB_genlatency.json")
    if int(latency["gencalls"]) != 30_015:
        raise AssertionError("latency call count mismatch")
    close(float(latency["genlat"]), 0.01248262762412127, label="pooled latency")

    pareto = load_json(SUMMARY_ROOT / "expB_pareto_bootstrap.json")
    if pareto != {
        "carr_nondom_pct": 100.0,
        "carr_dom_g5_pct": 99.97,
        "B": 10_000,
        "seed": 20260715,
    }:
        raise AssertionError("Pareto-bootstrap report mismatch")

    posthoc = load_json(REPO_ROOT / "reports" / "posthoc_review_sensitivity_2026-08-03.json")
    if (
        posthoc["status"] != "post_hoc_exploratory"
        or int(posthoc["rows"]) != 3_840
        or int(posthoc["roots"]) != 40
        or int(posthoc["bootstrap_samples"]) != 10_000
        or int(posthoc["seed"]) != 20260803
    ):
        raise AssertionError("post-hoc sensitivity report scope mismatch")


def verify_controlled_microbenchmark() -> None:
    """Recompute the controlled, development-only timing summary."""
    if not MICROBENCH_NOTE.is_file():
        raise AssertionError("controlled-resource note is missing")

    summary = load_json(MICROBENCH_SUMMARY)
    raw = load_json(MICROBENCH_RAW)
    with MICROBENCH_CSV.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    if summary.get("timing_evidence_valid") is not True:
        raise AssertionError("microbenchmark timing flag must be boolean true")
    if summary.get("evidence_class") != "development_descriptive":
        raise AssertionError("microbenchmark evidence class is not descriptive")
    if int(summary.get("n_runs", -1)) != 6 or int(summary.get("n_runs_per_method", -1)) != 2:
        raise AssertionError("microbenchmark sample size is not explicit")
    if raw.get("evidence_class") != "development" or raw.get("split") != "development":
        raise AssertionError("raw microbenchmark is not development-only")
    if raw.get("protocol", {}).get("timing_evidence_valid") is not True:
        raise AssertionError("raw microbenchmark timing flag is not true")
    if len(rows) != 6 or len(raw.get("runs", [])) != 6:
        raise AssertionError("microbenchmark must contain exactly six runs")

    required_columns = {
        "method",
        "seed",
        "total_generator_calls",
        "post_bootstrap_generation_count",
        "post_bootstrap_reactivation_count",
        "post_bootstrap_publication_count",
        "generator_seconds",
        "simulator_seconds",
        "elapsed_seconds",
        "timing_evidence_valid",
    }
    if not required_columns.issubset(rows[0]):
        raise AssertionError("microbenchmark CSV is missing auditable counters")

    raw_by_key = {(run["method"], int(run["seed"])): run for run in raw["runs"]}
    methods = {
        "context_memory_B25",
        "context_no_reactivation_B25",
        "exact_even_B25",
    }
    if {row["method"] for row in rows} != methods:
        raise AssertionError("microbenchmark method set mismatch")
    if {int(row["seed"]) for row in rows} != {17, 18}:
        raise AssertionError("microbenchmark seed set mismatch")
    if {row["workload"] for row in rows} != {"abrupt"}:
        raise AssertionError("microbenchmark workload mismatch")
    if {row["map_id"] for row in rows} != {"warehouse_small_narrow_kiva"}:
        raise AssertionError("microbenchmark map mismatch")

    for row in rows:
        key = (row["method"], int(row["seed"]))
        run = raw_by_key[key]
        budget = run["budget"]
        if row["timing_evidence_valid"].lower() != "true" or run.get("timing_evidence_valid") is not True:
            raise AssertionError(f"invalid timing flag for {key}")
        for column, raw_value in (
            ("total_generator_calls", budget["total_generator_calls"]),
            ("post_bootstrap_generation_count", budget["post_bootstrap_generation_count"]),
            ("post_bootstrap_reactivation_count", budget["post_bootstrap_reactivation_count"]),
            ("post_bootstrap_publication_count", budget["post_bootstrap_publication_count"]),
        ):
            if int(row[column]) != int(raw_value):
                raise AssertionError(f"microbenchmark counter mismatch for {key}: {column}")
        for column in ("generator_seconds", "simulator_seconds", "elapsed_seconds"):
            close(float(row[column]), float(run[column]), label=f"{key} {column}")

    for method in methods:
        selected = [row for row in rows if row["method"] == method]
        expected = summary["per_method"][method]
        for column, key in (
            ("total_generator_calls", "calls"),
            ("generator_seconds", "gen_s"),
            ("simulator_seconds", "sim_s"),
            ("elapsed_seconds", "elapsed_s"),
        ):
            close(fmean(float(row[column]) for row in selected), float(expected[key]), label=f"{method} {key}")

    run_level_latencies = [
        float(row["generator_seconds"]) / float(row["total_generator_calls"])
        for row in rows
    ]
    close(
        fmean(run_level_latencies),
        float(summary["per_call_gen_latency_s"]),
        label="unweighted per-run generator latency",
    )
    close(
        median(run_level_latencies),
        float(summary["per_call_gen_latency_median_s"]),
        label="median per-run generator latency",
    )
    pooled_latency = sum(float(row["generator_seconds"]) for row in rows) / sum(
        float(row["total_generator_calls"]) for row in rows
    )
    close(pooled_latency, float(summary["pooled_gen_latency_s"]), label="pooled generator latency")

    carr = summary["per_method"]["context_memory_B25"]
    dense = summary["per_method"]["exact_even_B25"]
    close(
        100.0 * (1.0 - float(carr["calls"]) / float(dense["calls"])),
        float(summary["microbench_call_reduction_pct"]),
        label="microbenchmark call reduction",
    )
    close(
        100.0 * (float(carr["elapsed_s"]) / float(dense["elapsed_s"]) - 1.0),
        float(summary["end_to_end_carr_vs_b25_pct"]),
        label="CARR end-to-end comparison",
    )
    close(
        100.0 * (1.0 - float(carr["gen_s"]) / float(dense["gen_s"])),
        float(summary["generator_only_reduction_pct"]),
        label="CARR generator-only reduction",
    )


def verify_manifest() -> None:
    manifest_path = ARTIFACT_ROOT / "ARTIFACT_SHA256.json"
    manifest = load_json(manifest_path)
    for relative_path, expected in manifest["sha256"].items():
        path = REPO_ROOT / relative_path
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise AssertionError(f"SHA-256 mismatch for {relative_path}: {actual}")


def verify_anonymity() -> None:
    forbidden = (
        b"/root/",
        b"/users/",
        b"seetacloud",
        b"autodl-container",
        b"maxiaoxiao",
        b"tj050512",
        b"@jd.com",
    )
    paths = list(RESULT_ROOT.rglob("*")) + [
        ARTIFACT_ROOT / "README.md",
        MICROBENCH_NOTE,
    ]
    for path in paths:
        if not path.is_file():
            continue
        data = path.read_bytes().lower()
        for token in forbidden:
            if token in data:
                raise AssertionError(f"machine-specific token {token!r} in {path}")


def main() -> None:
    os.chdir(REPO_ROOT)
    verify_g5cap()
    verify_threshold_sensitivity()
    verify_learned_holdout()
    verify_compact_diagnostics()
    verify_controlled_microbenchmark()
    verify_manifest()
    verify_anonymity()
    print("exploratory artifact summaries: PASS")


if __name__ == "__main__":
    main()
