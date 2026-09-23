#!/usr/bin/env python3
"""Deterministic regressions for the UPL-01 Maestro harness.

Covers the backend evidence verifier (positive + specific negative cases) and
static guards that keep the harness semantic, secret-free and validation-only.
Run: python scripts/test_upl01_maestro_contract.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import upl01_backend_evidence as evidence  # noqa: E402

FLOW_DIR = ROOT / "mobile/.maestro/upl01"
WORKFLOW = ROOT / ".github/workflows/upl-01-android-app-upload-e2e.yml"
FILENAME = "upl01-fixture.mp4"
SIZE = 123_456

GOOD_ROW = {
    "id": "7d6c1a64-1111-4222-8333-944455556666",
    "client_upload_id": "gallery_1790000000000_0_abc123defg",
    "batch_id": "batch_20260923_abc123",
    "storage_key": f"raw/batch_20260923_abc123/2026-09-23T10-00-00_{FILENAME}",
    "source_filename": FILENAME,
    "mime_type": "video/mp4",
    "status": "verified",
    "source_size_bytes": SIZE,
    "verified_size_bytes": SIZE,
    "verified_at": "2026-09-23T10:00:05Z",
    "source_size_evidence": "client_declared",
    "upload_protocol": "single_put",
    "created_at": "2026-09-23T10:00:00Z",
}
GOOD_VERIFY = {
    "ok": True,
    "exists": True,
    "storage_backend": "r2",
    "storage_key": GOOD_ROW["storage_key"],
    "size": SIZE,
    "upload_id": GOOD_ROW["id"],
    "upload_status": "verified",
}


def row(**overrides):
    value = copy.deepcopy(GOOD_ROW)
    value.update(overrides)
    return value


class BackendRowChecks(unittest.TestCase):
    def check(self, rows):
        return evidence.check_rows(rows, filename=FILENAME, fixture_bytes=SIZE)

    def test_exact_verified_row_passes(self):
        self.assertEqual(self.check([row()]), [])

    def test_no_row_fails_as_missing_upload(self):
        self.assertEqual(self.check([]), [f"expected exactly 1 source_uploads row for {FILENAME} since run start, found 0"])

    def test_extra_row_fails_so_negative_flows_cannot_silently_upload(self):
        self.assertIn("found 2", self.check([row(), row(id="other")])[0])

    def test_unverified_row_fails_on_status(self):
        self.assertEqual(self.check([row(status="uploading", verified_at=None)]), [
            "row.verified_at is empty",
            "row.status='uploading', expected 'verified'",
        ])

    def test_size_mismatch_row_fails_on_both_sizes(self):
        errors = self.check([row(status="size_mismatch", verified_size_bytes=SIZE - 1)])
        self.assertIn("row.status='size_mismatch', expected 'verified'", errors)
        self.assertIn(f"row.verified_size_bytes={SIZE - 1}, expected fixture size {SIZE}", errors)

    def test_declared_size_must_equal_fixture_bytes(self):
        self.assertEqual(self.check([row(source_size_bytes=SIZE + 1)]), [
            f"row.source_size_bytes={SIZE + 1}, expected fixture size {SIZE}",
        ])

    def test_multipart_protocol_is_not_the_gallery_path(self):
        self.assertEqual(self.check([row(upload_protocol="multipart")]), [
            "row.upload_protocol='multipart', expected 'single_put'",
        ])

    def test_non_gallery_client_id_fails(self):
        self.assertEqual(len(self.check([row(client_upload_id="external_123456789012")])), 1)

    def test_storage_key_outside_row_batch_fails(self):
        errors = self.check([row(storage_key=f"raw/other_batch/2026_{FILENAME}")])
        self.assertEqual(len(errors), 1)
        self.assertIn("is not raw/<batch_id>/<stamp>_", errors[0])


class VerifyApiChecks(unittest.TestCase):
    def check(self, status, body):
        return evidence.check_verify_response(status, body, row=GOOD_ROW, fixture_bytes=SIZE)

    def test_exact_r2_object_passes(self):
        self.assertEqual(self.check(200, GOOD_VERIFY), [])

    def test_missing_object_fails_specifically(self):
        errors = self.check(404, {"ok": False, "exists": False, "storage_backend": "r2", "storage_key": GOOD_ROW["storage_key"], "size": None})
        self.assertIn("verify API returned HTTP 404: None", errors)
        self.assertIn("verify.exists=False, expected True", errors)

    def test_size_mismatch_409_fails(self):
        errors = self.check(409, {"error": "Uploaded object size mismatch: expected 1, got 2"})
        self.assertEqual(errors[0], "verify API returned HTTP 409: 'Uploaded object size mismatch: expected 1, got 2'")

    def test_drive_fallback_is_not_r2_evidence(self):
        self.assertIn("verify.storage_backend='drive', expected 'r2'", self.check(200, {**GOOD_VERIFY, "storage_backend": "drive"}))

    def test_other_upload_id_fails(self):
        self.assertEqual(self.check(200, {**GOOD_VERIFY, "upload_id": "someone-else"}), [
            f"verify.upload_id='someone-else', expected {GOOD_ROW['id']!r}",
        ])


class HarnessContract(unittest.TestCase):
    def flow_texts(self):
        return {path.name: path.read_text() for path in FLOW_DIR.rglob("*.yaml")}

    def test_expected_flows_exist(self):
        names = set(self.flow_texts())
        self.assertTrue({"00-seed-media.yaml", "01-no-operator-secret.yaml", "02-picker-cancelled.yaml", "03-gallery-upload.yaml"} <= names)

    def test_flows_use_semantic_selectors_not_coordinates(self):
        for name, text in self.flow_texts().items():
            self.assertNotRegex(text, r"(?m)^\s*-?\s*point\s*:", name)
            self.assertNotRegex(text, r"\b\d{1,4}\s*,\s*\d{1,4}\b", name)
            self.assertNotIn("uiautomator", text, name)

    def test_secret_only_enters_through_runtime_env(self):
        texts = self.flow_texts()
        self.assertIn("inputText: ${MAESTRO_OPERATOR_SECRET}", texts["save-operator-secret.yaml"])
        for name, text in texts.items():
            for line in text.splitlines():
                if "inputText" in line:
                    self.assertIn("${MAESTRO_OPERATOR_SECRET}", line, name)

    def test_media_seeded_once_before_other_flows(self):
        texts = self.flow_texts()
        seeding = [name for name, text in texts.items() if "addMedia" in text]
        self.assertEqual(seeding, ["00-seed-media.yaml"])
        runner = (FLOW_DIR / "run-upl01.sh").read_text()
        order = [runner.index(f"run_flow {n}") for n in ("00-seed-media.yaml", "01-no-operator-secret.yaml", "02-picker-cancelled.yaml", "03-gallery-upload.yaml")]
        self.assertEqual(order, sorted(order))
        self.assertLess(runner.index("WINDOW_START="), order[0])

    def test_positive_flow_requires_success_alert_and_verified_row(self):
        text = self.flow_texts()["03-gallery-upload.yaml"]
        self.assertIn('assertVisible: "Uploaded to queue"', text)
        self.assertIn('id: "upload-item-status-verified"', text)

    def test_no_secret_flow_asserts_specific_reason(self):
        text = self.flow_texts()["01-no-operator-secret.yaml"]
        self.assertIn('assertVisible: "Some uploads failed"', text)
        self.assertIn('text: ".*Operator secret not set.*"', text)

    def test_media_fixtures_are_never_committed(self):
        self.assertEqual((FLOW_DIR / "media/.gitignore").read_text().splitlines()[1:], ["*", "!.gitignore"])

    def test_workflow_has_no_hand_written_ui_driver(self):
        text = WORKFLOW.read_text()
        for forbidden in ("uiautomator", "input tap", "input text", "window.xml"):
            self.assertNotIn(forbidden, text)
        self.assertIn("bash mobile/.maestro/upl01/run-upl01.sh", text)
        self.assertIn("concurrency:", text)

    def test_runner_keeps_backend_verification_and_scrubs_secrets(self):
        runner = (FLOW_DIR / "run-upl01.sh").read_text()
        self.assertIn("scripts/upl01_backend_evidence.py", runner)
        self.assertIn("scrub_secrets", runner)
        self.assertNotRegex(runner, r"\bsleep\b")

    def test_testids_used_by_flows_exist_in_app_source(self):
        source = "\n".join(p.read_text() for p in (ROOT / "mobile/src").rglob("*.tsx"))
        for test_id in ("operator-secret-input", "operator-secret-save", "pipeline-upload-gallery"):
            self.assertIn(f'testID="{test_id}"', source)
        self.assertIn("testID={`upload-item-status-${item.status}`}", source)

    def test_validation_bypass_never_enters_an_eas_build_profile(self):
        eas = json.loads((ROOT / "mobile/eas.json").read_text())
        for profile, config in eas["build"].items():
            self.assertNotIn("EXPO_PUBLIC_UPL01_OPERATOR_BYPASS", config.get("env", {}), profile)
        for workflow in (ROOT / ".github/workflows").glob("*.yml"):
            if workflow.name != WORKFLOW.name:
                self.assertNotIn("EXPO_PUBLIC_UPL01_OPERATOR_BYPASS", workflow.read_text(), workflow.name)


if __name__ == "__main__":
    unittest.main(verbosity=1)
