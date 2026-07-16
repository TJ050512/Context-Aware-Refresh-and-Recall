import importlib.util
import unittest
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPT = WORKSPACE / "scripts" / "analyze_gate0_validation.py"
SPEC = importlib.util.spec_from_file_location("analyze_gate0_validation", SCRIPT)
ANALYZER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ANALYZER)


def _artifact():
    seeds = list(range(101, 111))
    methods = ["uniform", "never", "candidate"]
    runs = []
    task_counts = {
        "uniform": [100] * 10,
        "never": [101] * 10,
        "candidate": [102, 101, 100, 100, 103, 99, 102, 100, 101, 104],
    }
    publication_counts = {
        "uniform": [0] * 10,
        "never": [1] * 10,
        "candidate": list(range(2, 12)),
    }
    for seed_index, seed in enumerate(seeds):
        for method in methods:
            runs.append(
                {
                    "method": method,
                    "seed": seed,
                    "num_task_finished": task_counts[method][seed_index],
                    "publication_count": publication_counts[method][seed_index],
                }
            )
    return {
        "schema": "dai.gate0.publication-mvp/v1",
        "status": "complete",
        "seeds": seeds,
        "methods": methods,
        "runs": runs,
    }


class ExactTestTests(unittest.TestCase):
    def test_exact_sign_flip_is_exhaustive_and_two_sided(self):
        result = ANALYZER.exact_paired_sign_flip([1, 1, 1])
        self.assertEqual(result["total_assignments"], 8)
        self.assertEqual(result["extreme_assignments"], 2)
        self.assertEqual(result["p_value"], 0.25)

    def test_zero_deltas_have_unit_p_value(self):
        result = ANALYZER.exact_paired_sign_flip([0] * 10)
        self.assertEqual(result["nonzero_pairs"], 0)
        self.assertEqual(result["p_value"], 1.0)


class ValidationAnalysisTests(unittest.TestCase):
    def test_complete_analysis_has_paired_metrics_and_publications(self):
        analysis = ANALYZER.analyze_artifact(
            _artifact(), bootstrap_samples=2_000, bootstrap_seed=17
        )
        self.assertEqual(analysis["analysis_scope"]["num_seeds"], 10)
        self.assertEqual(analysis["analysis_scope"]["evidence_class"], "diagnostic")
        self.assertFalse(analysis["analysis_scope"]["sota_claim_permitted"])

        candidate = analysis["methods"]["candidate"]
        vs_uniform = candidate["comparisons"]["uniform"]
        self.assertEqual(
            list(vs_uniform["paired_deltas_by_seed"].values()),
            [2, 1, 0, 0, 3, -1, 2, 0, 1, 4],
        )
        self.assertEqual(vs_uniform["mean_delta_num_task_finished"], 1.2)
        self.assertEqual(vs_uniform["median_delta_num_task_finished"], 1.0)
        self.assertEqual(
            vs_uniform["win_tie_loss"], {"wins": 6, "ties": 3, "losses": 1}
        )
        self.assertEqual(vs_uniform["n_pairs"], 10)
        self.assertEqual(len(vs_uniform["paired_bootstrap_95_ci_mean_delta"]), 2)

        publications = candidate["publication_counts"]
        self.assertEqual(publications["counts_by_seed"]["101"], 2)
        self.assertEqual(publications["mean"], 6.5)
        self.assertEqual(publications["median"], 6.5)
        self.assertEqual(publications["total"], 65)

    def test_bootstrap_is_reproducible_for_fixed_seed(self):
        first = ANALYZER.paired_bootstrap_mean_ci(
            [2, 1, 0, -1], samples=1_000, seed=20260714
        )
        second = ANALYZER.paired_bootstrap_mean_ci(
            [2, 1, 0, -1], samples=1_000, seed=20260714
        )
        self.assertEqual(first, second)

    def test_missing_pair_is_rejected(self):
        artifact = _artifact()
        artifact["runs"] = artifact["runs"][:-1]
        with self.assertRaisesRegex(
            ANALYZER.ArtifactValidationError, "complete paired grid"
        ):
            ANALYZER.analyze_artifact(artifact, bootstrap_samples=10)

    def test_wrong_validation_split_is_rejected(self):
        artifact = _artifact()
        artifact["seeds"][-1] = 1001
        artifact["runs"][-3]["seed"] = 1001
        artifact["runs"][-2]["seed"] = 1001
        artifact["runs"][-1]["seed"] = 1001
        with self.assertRaisesRegex(
            ANALYZER.ArtifactValidationError, "validation seeds must be exactly"
        ):
            ANALYZER.analyze_artifact(artifact, bootstrap_samples=10)

    def test_fewer_than_ten_expected_seeds_is_rejected(self):
        with self.assertRaisesRegex(
            ANALYZER.ArtifactValidationError, "exactly 10 expected seeds"
        ):
            ANALYZER.analyze_artifact(
                _artifact(),
                expected_seeds=list(range(101, 110)),
                bootstrap_samples=10,
            )


if __name__ == "__main__":
    unittest.main()
