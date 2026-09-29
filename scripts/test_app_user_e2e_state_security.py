#!/usr/bin/env python3
import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import app_user_e2e_evidence as evidence


class E2EStateSecurityTest(unittest.TestCase):
    def test_seed_never_persists_passwords(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            args = argparse.Namespace(
                marker="security-regression",
                email="primary@example.com",
                password="PRIMARY-SECRET-Aa9!",
                other_email="other@example.com",
                other_password="OTHER-SECRET-Aa9!",
            )
            with (
                patch.object(evidence, "STATE", state),
                patch.object(evidence, "require_service"),
                patch.object(evidence, "create_user", side_effect=["primary-id", "secondary-id"]),
                patch.object(evidence, "wait_for_profile"),
                patch.object(evidence, "service_patch"),
            ):
                evidence.seed(args)

            raw = state.read_text(encoding="utf-8")
            data = json.loads(raw)
            self.assertNotIn("password", data)
            self.assertNotIn("other_password", data)
            self.assertNotIn(args.password, raw)
            self.assertNotIn(args.other_password, raw)
            self.assertEqual(data["primary_id"], "primary-id")
            self.assertEqual(data["secondary_id"], "secondary-id")


if __name__ == "__main__":
    unittest.main()
