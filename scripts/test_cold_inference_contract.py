"""Pure-stdlib regression checks for mandatory cold inference, all sports."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ColdInferenceGateTest(unittest.TestCase):
    def test_disabled_cache_and_no_evaluation_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".git").mkdir()
            (root / "evaluation/ground_truth").mkdir(parents=True)
            (root / "evaluation/ground_truth/GT.json").write_text("historical marker")
            (root / "raw").mkdir()
            (root / "raw/source.mp4").write_text("current media should remain")
            env = os.environ.copy()
            env.update({
                "GITHUB_ACTIONS": "true",
                "SPORTREEL_STRICT_COLD_INFERENCE": "1",
                "LLM_CACHE": "0",
                "SPORTREEL_IDENTITY_REVIEW_DECISIONS": "",
            })
            preflight = ROOT / "scripts/assert_cold_inference.py"
            before = subprocess.run(
                [sys.executable, str(preflight)],
                cwd=root, env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(before.returncode, 0)
            self.assertIn("Evaluation-only", before.stderr)
            after = subprocess.run(
                [sys.executable, str(preflight), "--prepare"],
                cwd=root, env=env, capture_output=True, text=True,
            )
            self.assertEqual(after.returncode, 0, after.stderr)
            self.assertFalse((root / "evaluation/ground_truth").exists())
            self.assertTrue((root / "raw/source.mp4").exists())

    def test_cache_and_identity_decision_override_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".git").mkdir()
            base = dict(os.environ, GITHUB_ACTIONS="true", SPORTREEL_STRICT_COLD_INFERENCE="1",
                        LLM_CACHE="0", SPORTREEL_IDENTITY_REVIEW_DECISIONS="")
            script = str(ROOT / "scripts/assert_cold_inference.py")
            for override in ({"LLM_CACHE": "1"}, {"SPORTREEL_IDENTITY_REVIEW_DECISIONS": "/tmp/old.json"}):
                env = dict(base, **override)
                p = subprocess.run([sys.executable, script], cwd=root, env=env, capture_output=True, text=True)
                self.assertNotEqual(p.returncode, 0)

    def test_workflows_do_not_restore_model_decision_cache(self):
        workflows = (
            ROOT / ".github/workflows/pipeline-run.yml",
            ROOT / ".github/workflows/pipeline-qualification-run.yml",
        )
        for path in workflows:
            with self.subTest(path=path):
                s = path.read_text(encoding="utf-8")
                self.assertNotIn("- name: Restore LLM analysis cache", s)
                self.assertNotIn("- name: Save LLM analysis cache", s)
                self.assertIn("LLM_CACHE: '0'", s)
                self.assertIn("SPORTREEL_IDENTITY_REVIEW_DECISIONS: ''", s)
                self.assertIn("python scripts/assert_cold_inference.py --prepare", s)


if __name__ == "__main__":
    unittest.main()
