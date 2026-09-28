#!/usr/bin/env python3
"""Contract guard for the Review -> real delivery -> Discover qualification path."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "app_review_delivery_e2e.py"
RUNNER = ROOT / "mobile" / ".maestro" / "app-e2e" / "run-review-delivery.sh"


class ReviewDeliveryQualificationContract(unittest.TestCase):
    def test_runner_waits_for_real_delivery_instead_of_seeding_discover(self):
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("verify-delivery-discover", runner)
        self.assertNotIn("verify-approval-cancel", runner)
        self.assertNotIn("seed-discover", runner)

    def test_helper_exposes_real_delivery_verifier_and_no_synthetic_discover_command(self):
        helper = HELPER.read_text(encoding="utf-8")
        self.assertIn("def wait_for_approval_and_delivery", helper)
        self.assertIn('"verify-delivery-discover"', helper)
        self.assertNotIn('"seed-discover"', helper)


if __name__ == "__main__":
    unittest.main()
