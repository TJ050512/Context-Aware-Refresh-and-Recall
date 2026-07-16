from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPACT_CSV = ROOT / "results" / "same_call_confirmation_b" / "compact_runs.csv"
COMPACT_REPORT = ROOT / "reports" / "compact_b_analysis.json"


def load_module(name: str, relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANALYZER = load_module("test_analyze_compact_b", "scripts/analyze_compact_b.py")


class CompactBArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = ANALYZER.analyze_file(COMPACT_CSV)
        cls.committed = json.loads(COMPACT_REPORT.read_text(encoding="utf-8"))

    def test_compact_csv_is_complete_path_free_and_pairable(self) -> None:
        with COMPACT_CSV.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(tuple(reader.fieldnames or ()), ANALYZER.FIELDS)
            rows = list(reader)
        self.assertEqual(len(rows), 3840)
        self.assertFalse(
            any(
                "/" in value or "\\" in value or "@" in value
                for row in rows
                for value in row.values()
            )
        )
        groups: dict[tuple[str, str, str], set[str]] = {}
        for row in rows:
            key = (row["scenario"], row["root_seed"], row["workload"])
            groups.setdefault(key, set()).add(row["pairing_fingerprint"])
        self.assertEqual(len(groups), 480)
        self.assertTrue(all(len(values) == 1 for values in groups.values()))

    def test_committed_analysis_is_exactly_reproducible(self) -> None:
        self.assertEqual(self.generated, self.committed)
        self.assertEqual(
            self.generated["schema"],
            "dai.compact-same-call-confirmation-analysis/b-v1",
        )
        self.assertTrue(self.generated["audit"]["passed"])
        self.assertEqual(self.generated["audit"]["row_count"], 3840)
        self.assertEqual(self.generated["audit"]["paired_groups"], 480)

    def test_method_summaries_match_committed_reference(self) -> None:
        for method in ANALYZER.METHODS:
            compact = self.generated["method_summaries"][method]
            reference = self.committed["method_summaries"][method]
            self.assertEqual(compact["n_runs"], reference["n_runs"])
            for field in (
                "tasks",
                "total_generator_calls",
                "post_bootstrap_generations",
                "effective_switches",
                "reactivations",
            ):
                self.assertEqual(compact[field], reference[field], (method, field))

    def test_primary_noninferiority_matches_committed_reference(self) -> None:
        compact = self.generated["noninferiority_vs_exact_even_B25"]
        reference = self.committed["noninferiority_vs_exact_even_B25"]
        for field in (
            "candidate",
            "comparator",
            "relative_margin",
            "checks",
            "passed",
        ):
            self.assertEqual(compact[field], reference[field], field)
        for field in (
            "root_relative_effects",
            "mean_relative_effect",
            "mean_relative_effect_percent",
            "median_root_relative_effect",
            "mean_absolute_task_delta",
            "root_win_tie_loss",
            "cluster_bootstrap",
            "map_effects",
            "workload_effects",
            "scenario_effects",
        ):
            self.assertEqual(
                compact["comparison"][field],
                reference["comparison"][field],
                field,
            )
        self.assertEqual(
            compact["shifted_exact_sign_flip"],
            reference["shifted_exact_sign_flip"],
        )

    def test_superiority_and_holm_match_committed_reference(self) -> None:
        for comparator in ANALYZER.SUPERIORITY_COMPARATORS:
            compact = self.generated["superiority_comparisons"][comparator]
            reference = self.committed["superiority_comparisons"][comparator]
            for field in (
                "root_relative_effects",
                "mean_relative_effect",
                "mean_relative_effect_percent",
                "median_root_relative_effect",
                "mean_absolute_task_delta",
                "root_win_tie_loss",
                "cluster_bootstrap",
                "exact_sign_flip",
                "map_effects",
                "workload_effects",
                "scenario_effects",
            ):
                self.assertEqual(compact[field], reference[field], (comparator, field))
        self.assertEqual(
            self.generated["multiplicity"],
            self.committed["multiplicity"],
        )

    def test_pareto_matches_committed_reference(self) -> None:
        self.assertEqual(self.generated["pareto"], self.committed["pareto"])

    def test_meet_in_the_middle_matches_exact_enumeration(self) -> None:
        effects = [
            0.013,
            -0.007,
            0.021,
            0.004,
            -0.009,
            0.016,
            -0.003,
            0.011,
            -0.014,
            0.006,
            0.008,
            -0.002,
        ]
        enumerated = ANALYZER._exact_sign_flip_enumerated(effects)
        mitm = ANALYZER._exact_sign_flip_mitm(effects)
        self.assertEqual(mitm, enumerated)


if __name__ == "__main__":
    unittest.main()
