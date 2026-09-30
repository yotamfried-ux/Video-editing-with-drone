#!/usr/bin/env python3
"""Contract for the non-destructive phone-ready Android build workflow."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "android-phone-ready-build.yml"


class PhoneReadyAndroidBuildContract(unittest.TestCase):
    def test_build_is_non_destructive_and_exact(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("eas build --platform android --profile preview --non-interactive --no-wait --json", workflow)
        self.assertIn("eas build:view", workflow)  # exact build is polled to a terminal state
        self.assertIn("eas build:download", workflow)
        self.assertIn("--build-id", workflow)
        self.assertIn("scripts/record_eas_build_evidence.py", workflow)
        self.assertIn("sportreel-phone-ready-", workflow)
        self.assertNotIn("remove_biometric_storage.py", workflow)
        self.assertNotIn("apply_upload_release_migrations.py", workflow)
        self.assertNotIn("confirm_biometric_removal", workflow)
        self.assertNotIn("EXPO_PUBLIC_UPL01_OPERATOR_BYPASS", workflow)

    def test_build_runs_only_on_main_or_explicit_dispatch(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("branches: [main]", workflow)


if __name__ == "__main__":
    unittest.main()
