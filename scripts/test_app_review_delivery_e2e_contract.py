#!/usr/bin/env python3
"""Contract guard for the Review -> real delivery -> Discover qualification path."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "app_review_delivery_e2e.py"
RUNNER = ROOT / "mobile" / ".maestro" / "app-e2e" / "run-review-delivery.sh"
DISCOVER_FLOW = ROOT / "mobile" / ".maestro" / "app-e2e" / "05-discover-fixture.yaml"
REEL_THUMB = ROOT / "mobile" / "src" / "features" / "sessions" / "components" / "ReelThumb.tsx"


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

    def test_discover_assertion_is_bound_to_the_exact_created_reel(self):
        runner = RUNNER.read_text(encoding="utf-8")
        flow = DISCOVER_FLOW.read_text(encoding="utf-8")
        thumb = REEL_THUMB.read_text(encoding="utf-8")
        self.assertIn("DISCOVER_REEL_ID", runner)
        self.assertIn('reel-thumb-${DISCOVER_REEL_ID}-live', flow)
        self.assertIn("reel-thumb-${reel.id}-${badgeType}", thumb)

    def test_real_delivery_requires_provider_notification_evidence(self):
        helper = HELPER.read_text(encoding="utf-8")
        self.assertIn("notification_message_ids", helper)
        self.assertIn("notification_provider", helper)


if __name__ == "__main__":
    unittest.main()
