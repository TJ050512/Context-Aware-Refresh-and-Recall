from __future__ import annotations

import hashlib
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CarrRlLiteArtifactTests(unittest.TestCase):
    def test_dev_runner_is_reproducible_from_frozen_runner(self) -> None:
        frozen = ROOT / "scripts" / "run_same_call_confirmation_v1.py"
        self.assertEqual(
            hashlib.sha256(frozen.read_bytes()).hexdigest(),
            "998e321877e660b5d13618b74905040df258f95657490e764e92cc4b117194eb",
        )
        generated = ROOT / "carr_rl_lite_exp" / "scripts" / "run_carr_rl_lite_dev.py"
        before = generated.read_bytes()
        subprocess.run(
            [sys.executable, str(ROOT / "carr_rl_lite_exp" / "scripts" / "make_dev_runner.py")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(generated.read_bytes(), before)

    def test_public_exploratory_summaries(self) -> None:
        subprocess.run(
            [
                sys.executable,
                str(
                    ROOT
                    / "carr_rl_lite_exp"
                    / "scripts"
                    / "verify_public_summaries.py"
                ),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_posthoc_report_is_byte_reproducible(self) -> None:
        output = ROOT / "reproduced" / "posthoc_review_sensitivity_2026-08-03.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "analyze_posthoc_review_sensitivity.py"),
                "--csv",
                "results/same_call_confirmation_b/compact_runs.csv",
                "--output",
                str(output),
                "--seed",
                "20260803",
                "--bootstrap-samples",
                "10000",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        expected = ROOT / "reports" / "posthoc_review_sensitivity_2026-08-03.json"
        self.assertEqual(output.read_bytes(), expected.read_bytes())


if __name__ == "__main__":
    unittest.main()
