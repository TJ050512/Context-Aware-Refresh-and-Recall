from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
FORMAL = ROOT / "scripts" / "run_same_call_confirmation_matrix_b.sh"
SMOKE = ROOT / "scripts" / "run_same_call_smoke_b.sh"


class ExperimentBLaunchContractTests(unittest.TestCase):
    def test_bash_syntax(self):
        for script in (FORMAL, SMOKE):
            with self.subTest(script=script.name):
                subprocess.run(["bash", "-n", str(script)], check=True)

    def test_formal_launcher_is_config_bound_and_effect_blind(self):
        text = FORMAL.read_text(encoding="utf-8")
        self.assertIn("execution.jobs_per_scenario", text)
        self.assertIn('--jobs "$JOBS_PER_SCENARIO"', text)
        self.assertIn('config.get("execution_host") != target.get("execution_host")', text)
        self.assertIn('target.get("execution_host") != current_host', text)
        self.assertIn('execution.get("runs_per_scenario") != 960', text)
        self.assertIn('execution.get("attempt_ledger_events_per_scenario") != 1920', text)
        self.assertIn('execution.get("total_runs") != 3840', text)
        self.assertIn("--preflight-only", text)
        self.assertIn("runs=3840", text)
        self.assertIn("ledger_events=1920", text)
        self.assertIn("effect_inference_performed\": False", text)
        self.assertNotIn("analyze_same_call_confirmation_b.py", text)
        self.assertNotIn("same_call_confirmation_a2", text)
        self.assertNotIn("dai-same-call-confirmatory-a2-pid-reuse-correction", text)
        self.assertNotIn("connect.west", text)
        self.assertNotRegex(text, re.compile(r"sshpass|password", re.IGNORECASE))

    def test_formal_launcher_has_all_or_nothing_counts_and_scenarios(self):
        text = FORMAL.read_text(encoding="utf-8")
        for label in ("narrow_r020", "narrow_r035", "regular_r020", "regular_r035"):
            self.assertIn(f"launch {label}", text)
        for token in (
            "exactly 40 integer roots",
            "len(lines) != 1920",
            'record.get("started_events") != 960',
            'record.get("completed_events") != 960',
            "len(all_runs) != 3840",
            "len(set(all_process_instances)) != 3840",
            "len(set(all_run_uuids)) != 3840",
            "len(cell_groups) != 480",
        ):
            self.assertIn(token, text)

    def test_smoke_never_uses_confirmation_roots(self):
        text = SMOKE.read_text(encoding="utf-8")
        self.assertIn("--split development", text)
        self.assertIn("--seeds 17", text)
        self.assertIn("--workloads stationary", text)
        self.assertIn('artifact.get("seeds") != [17]', text)
        self.assertIn("set(artifact.get(\"seeds\", ())) & B_ROOTS", text)
        self.assertIn('"b_root_runs_observed": 0', text)
        self.assertIn('"effect_inference_performed": False', text)
        self.assertNotIn("--split same_call_confirmation_v1", text)
        self.assertNotIn("connect.west", text)

    def test_smoke_uses_full_scientific_contract_and_separate_paths(self):
        text = SMOKE.read_text(encoding="utf-8")
        for method in (
            "bootstrap_only", "exact_even_G4", "exact_even_G5", "random_G5",
            "js_cap_G5", "context_no_reactivation_B25", "context_memory_B25",
            "exact_even_B25",
        ):
            self.assertIn(method, text)
        for token in (
            "--warmup-time 200", "--horizon 2000", "--decision-window 20",
            "--release-interval 110", "--guard-suffix 4", "--sigma 0.75",
            "--context-match-threshold 0.05", "--context-recall-margin 0.02",
            "--context-min-score 0.10", "--context-min-gap 6",
            "--context-maintenance-age 25", "--context-maintenance-stability 0.20",
            "--fresh-process-per-arm", "--attempt-ledger", "--output",
        ):
            self.assertIn(token, text)
        self.assertIn("results/same_call_smoke_b", text)
        self.assertIn("logs/same_call_smoke_b", text)
        self.assertIn("reports/same_call_smoke_b.json", text)


if __name__ == "__main__":
    unittest.main()
