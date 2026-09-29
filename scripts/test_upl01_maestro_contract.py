#!/usr/bin/env python3
"""Deterministic regressions for the UPL-01 Maestro harness.

Covers the backend evidence verifier (positive + specific negative cases) and
static guards that keep the harness semantic, secret-free and validation-only.
Run: python scripts/test_upl01_maestro_contract.py
"""

from __future__ import annotations

import yaml
import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import upl01_backend_evidence as evidence  # noqa: E402

sys.path.insert(0, str(ROOT / "mobile/.maestro/upl01"))
import summarize_failure  # noqa: E402

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
        return evidence.check_rows(rows, fixture_bytes=SIZE)

    def test_exact_verified_row_passes(self):
        self.assertEqual(self.check([row()]), [])

    def test_no_row_fails_as_missing_upload(self):
        self.assertEqual(self.check([]), [f"expected exactly 1 gallery source_uploads row of {SIZE} bytes since run start, found 0"])

    def test_negative_backend_check_passes_only_with_zero_rows(self):
        self.assertEqual(evidence.check_no_rows([], fixture_bytes=SIZE), [])
        self.assertEqual(
            evidence.check_no_rows([row()], fixture_bytes=SIZE),
            [f"expected 0 gallery source_uploads rows of {SIZE} bytes since run start, found 1"],
        )

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

    def test_media_store_display_name_is_recorded_not_required(self):
        # Run 35896137923: the Android 13+ Photo Picker path stored
        # source_filename "1000000016.mp4" (a MediaStore id) for the fixture.
        name = "1000000016.mp4"
        self.assertEqual(self.check([row(source_filename=name, storage_key=f"raw/batch_20260923_abc123/2026-09-23T17-38-00_{name}")]), [])

    def test_empty_filename_fails(self):
        self.assertIn("row.source_filename is empty", self.check([row(source_filename="")]))

    def test_storage_key_must_end_with_the_row_filename(self):
        errors = self.check([row(source_filename="1000000016.mp4")])
        self.assertEqual(len(errors), 1)
        self.assertIn("is not raw/<batch_id>/<stamp>_1000000016.mp4", errors[0])

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


class FailureSummary(unittest.TestCase):
    """The step-log summary must name the failing command and on-screen labels."""

    def test_reports_failed_command_junit_reason_and_screen(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            flow = root / "maestro-01-no-operator-secret"
            flow.mkdir()
            (flow / "commands-(01-no-operator-secret.yaml).json").write_text(json.dumps([
                {"command": {"launchAppCommand": {"appId": "com.sportreel.app"}}, "metadata": {"status": "COMPLETED"}},
                {"command": {"assertConditionCommand": {"condition": {"visible": {"textRegex": "No secret"}}}},
                 "metadata": {"status": "FAILED", "error": {"message": "Assertion is false: \"No secret\" is visible"}}},
            ]))
            (flow / "maestro.log").write_text("12:00 INFO ok\n12:01 [ERROR] maestro.MaestroException$AssertionFailure: Assertion is false\n")
            (root / "01-no-operator-secret.junit.xml").write_text(
                '<testsuites><testsuite><testcase name="x"><failure message="Assertion is false: No secret"/></testcase></testsuite></testsuites>'
            )
            (root / "final-maestro-hierarchy.json").write_text(json.dumps(
                {"attributes": {}, "children": [
                    {"attributes": {"text": "Operator Secret"}, "children": []},
                    {"attributes": {"resource-id": "operator-secret-input", "hintText": "Paste the operator secret here"}, "children": []},
                ]}
            ))
            failures = summarize_failure.junit_failures(root) + summarize_failure.failed_commands(root)
            self.assertEqual(failures[0], "01-no-operator-secret.junit.xml: Assertion is false: No secret")
            self.assertIn("FAILED assertConditionCommand", failures[1])
            self.assertIn("Assertion is false", failures[1])
            self.assertEqual(len(failures), 2, "COMPLETED commands must not be reported")
            self.assertEqual(len(summarize_failure.log_errors(root)), 1)
            self.assertEqual(summarize_failure.visible_nodes(root / "final-maestro-hierarchy.json"), [
                "text='Operator Secret'",
                "resource-id='operator-secret-input' hintText='Paste the operator secret here'",
            ])

    def test_runner_summarizes_only_after_scrubbing(self):
        runner = (FLOW_DIR / "run-upl01.sh").read_text()
        body = runner[runner.index("on_exit() {"):]
        self.assertLess(body.index("scrub_secrets"), body.index("summarize_failure.py"))


class HarnessContract(unittest.TestCase):
    def flow_texts(self):
        return {path.name: path.read_text() for path in FLOW_DIR.rglob("*.yaml")}

    def test_expected_flows_exist(self):
        names = set(self.flow_texts())
        self.assertTrue({"00-seed-media.yaml", "01-no-operator-secret.yaml", "02-picker-cancelled.yaml", "03-gallery-upload.yaml", "04-offline-retry.yaml", "05-restart-retry.yaml"} <= names)

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

    def test_isolated_wrappers_keep_seed_and_behavior_in_one_maestro_process(self):
        texts = self.flow_texts()
        seeding = [name for name, text in texts.items() if "addMedia" in text]
        self.assertEqual(seeding, ["00-seed-media.yaml"])
        expected = {
            "10-isolated-no-operator-secret.yaml": "01-no-operator-secret.yaml",
            "11-isolated-picker-cancelled.yaml": "02-picker-cancelled.yaml",
            "12-isolated-gallery-upload.yaml": "03-gallery-upload.yaml",
            "13-isolated-offline-retry.yaml": "04-offline-retry.yaml",
            "14-isolated-restart-retry.yaml": "05-restart-retry.yaml",
        }
        for wrapper, behavior in expected.items():
            self.assertIn("runFlow: 00-seed-media.yaml", texts[wrapper])
            self.assertIn(f"runFlow: {behavior}", texts[wrapper])

        runner = (FLOW_DIR / "run-upl01-scenario.sh").read_text()
        self.assertNotIn("run_flow 00-seed-media.yaml", runner)
        self.assertEqual(runner.count('run_flow "$FLOW"'), 2)
        self.assertIn("post-flow-hierarchy.json", runner)
        self.assertIn("Pixel Launcher isn.t responding", runner)
        self.assertIn('if [ "$flow_code" -ne 0 ]; then', runner)
        self.assertIn('if [ "$EXPECTATION" = "no-upload" ]', runner)
        self.assertIn("--expect no-upload", runner)
        self.assertIn("pre-retry-backend-evidence.json", runner)
        self.assertIn("refusing positive-flow retry because backend state is not empty", runner)
        self.assertIn("retrying once after a failed flow with verified-safe backend state", runner)
        self.assertLess(runner.index("WINDOW_START="), runner.index('run_flow "$FLOW"'))

    def test_positive_flow_requires_success_alert_and_verified_row(self):
        text = self.flow_texts()["03-gallery-upload.yaml"]
        self.assertIn('assertVisible: "Uploaded to queue"', text)
        self.assertIn('id: "upload-item-status-verified"', text)
        # The picker may hand the app a MediaStore display name, so the UI row
        # must not be matched on the fixture filename (run 35896137923).
        self.assertNotIn('assertVisible: "upl01-fixture.mp4"', text)

    def test_upload_rows_are_scrolled_into_view_before_assertion(self):
        # Rows render below the fold (and under the debug LogBox banner);
        # assertVisible only sees on-screen nodes (run 35895173989).
        texts = self.flow_texts()
        for flow, row_id in (("01-no-operator-secret.yaml", "upload-item-status-failed"),
                             ("03-gallery-upload.yaml", "upload-item-status-verified"),
                             ("04-offline-retry.yaml", "upload-item-status-verified"),
                             ("05-restart-retry.yaml", "upload-item-status-verified")):
            text = texts[flow]
            scroll = text.find(f'scrollUntilVisible:\n    element:\n      id: "{row_id}"')
            self.assertGreaterEqual(scroll, 0, flow)
            self.assertLess(scroll, text.index(f'id: "{row_id}"\n    text:'), flow)

    def test_no_secret_flow_asserts_specific_reason(self):
        text = self.flow_texts()["01-no-operator-secret.yaml"]
        self.assertIn('assertVisible: "Some uploads failed"', text)
        self.assertIn('text: ".*Operator secret not set.*"', text)

    def test_offline_retry_flow_uses_maestro_network_control_and_verified_retry(self):
        text = self.flow_texts()["04-offline-retry.yaml"]
        self.assertIn("setAirplaneMode: enabled", text)
        self.assertIn("setAirplaneMode: disabled", text)
        self.assertIn('id: "pipeline-retry-all-failed"', text)
        self.assertIn('id: "upload-item-status-failed"', text)
        self.assertIn('id: "upload-item-status-verified"', text)

    def test_restart_retry_flow_uses_real_process_death_and_verified_retry(self):
        text = self.flow_texts()["05-restart-retry.yaml"]
        self.assertIn("setAirplaneMode: enabled", text)
        self.assertIn("pressKey: Home", text)
        self.assertIn("killApp", text)
        self.assertIn("stopApp: false", text)
        self.assertIn("setAirplaneMode: disabled", text)
        self.assertIn('id: "pipeline-retry-all-failed"', text)
        self.assertIn('id: "upload-item-status-verified"', text)

    def test_gallery_upload_queue_is_persisted_before_network_and_restored_after_restart(self):
        source = (ROOT / "mobile/src/app/(operator)/pipeline.tsx").read_text()
        self.assertIn("GALLERY_UPLOAD_QUEUE_KEY", source)
        self.assertIn("restoreGalleryUploadQueue()", source)
        self.assertIn("await persistGalleryUploadQueue(items)", source)
        self.assertIn("clientUploadId", source)
        self.assertIn("Upload interrupted by app restart", source)

    def test_media_fixtures_are_never_committed(self):
        self.assertEqual((FLOW_DIR / "media/.gitignore").read_text().splitlines()[1:], ["*", "!.gitignore"])

    def test_workflow_has_no_hand_written_ui_driver(self):
        text = WORKFLOW.read_text()
        for forbidden in ("uiautomator", "input tap", "input text", "window.xml"):
            self.assertNotIn(forbidden, text)
        self.assertIn("bash mobile/.maestro/upl01/run-upl01-scenario.sh", text)
        self.assertIn("concurrency:", text)
        workflow = yaml.safe_load(text)
        self.assertTrue(workflow["concurrency"]["cancel-in-progress"])
        self.assertEqual(workflow["concurrency"]["group"], "upl-01-android-app-upload-e2e")
        self.assertIn("max-parallel: 3", text)

    def test_parallel_workflow_prepares_apk_once_and_runs_five_scenarios(self):

        jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
        prepare = jobs["prepare-apk"]
        scenario = jobs["upl-01-scenario"]
        self.assertEqual(scenario["strategy"]["max-parallel"], 3)
        self.assertFalse(scenario["strategy"]["fail-fast"])
        matrix = scenario["strategy"]["matrix"]["include"]
        self.assertEqual(
            {entry["scenario"] for entry in matrix},
            {"no-operator-secret", "picker-cancelled", "gallery-upload", "offline-retry", "restart-retry"},
        )
        self.assertEqual(len({(entry["duration"], entry["size"], entry["frequency"]) for entry in matrix}), 5)
        self.assertEqual(scenario["needs"], "prepare-apk")

        prepare_steps = {step.get("name") or step.get("uses"): step for step in prepare["steps"]}
        self.assertIn("cache-hit", prepare_steps["Build Android debug APK"]["if"])
        self.assertEqual(
            prepare_steps["Publish APK once for parallel scenario workers"]["uses"],
            "actions/upload-artifact@v4",
        )

        scenario_steps = {step.get("name") or step.get("uses"): step for step in scenario["steps"]}
        self.assertNotIn("if", scenario_steps["Install mobile dependencies"])
        self.assertEqual(
            scenario_steps["Download prepared APK"]["uses"],
            "actions/download-artifact@v4",
        )
        self.assertIn("run-upl01-scenario.sh", scenario_steps["Run isolated UPL-01 Maestro scenario"]["with"]["script"])

    def test_apk_checkpoint_hashes_native_inputs_not_app_js(self):
        workflows = [
            WORKFLOW,
            ROOT / ".github/workflows/full-android-app-qualification.yml",
        ]
        for workflow_path in workflows:
            text = workflow_path.read_text()
            self.assertIn("mobile/package-lock.json", text, workflow_path.name)
            self.assertIn("mobile/app.json", text, workflow_path.name)
            self.assertIn("mobile/plugins mobile/modules mobile/assets", text, workflow_path.name)
            self.assertIn("mobile/scripts/postinstall.js", text, workflow_path.name)
            self.assertNotIn("KEY=$(find mobile -type f", text, workflow_path.name)

    def test_parallel_runner_keeps_backend_verification_and_scrubs_secrets(self):
        runner = (FLOW_DIR / "run-upl01-scenario.sh").read_text()
        self.assertIn("scripts/upl01_backend_evidence.py", runner)
        self.assertIn('--expect "$EXPECTATION"', runner)
        self.assertIn("scrub_secrets", runner)
        self.assertIn("stabilize_adb_device", runner)
        self.assertIn("adb kill-server", runner)
        self.assertIn("adb start-server", runner)
        self.assertIn("adb wait-for-device", runner)
        self.assertIn("for attempt in 1 2 3 4 5 6", runner)
        stabilizer = re.search(
            r"stabilize_adb_device\(\) \{.*?^\}",
            runner,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(stabilizer)
        runner_without_stabilizer = runner[: stabilizer.start()] + runner[stabilizer.end() :]
        self.assertNotRegex(runner_without_stabilizer, r"\bsleep\b")
        self.assertIn('EXPECTATION="no-upload"', runner)
        self.assertIn('EXPECTATION="verified-upload"', runner)

    def test_testids_used_by_flows_exist_in_app_source(self):
        source = "\n".join(p.read_text() for p in (ROOT / "mobile/src").rglob("*.tsx"))
        for test_id in ("operator-secret-input", "operator-secret-save", "pipeline-upload-gallery", "pipeline-retry-all-failed"):
            self.assertIn(f'testID="{test_id}"', source)
        self.assertIn("testID={`upload-item-status-${item.status}`}", source)

    def test_api_error_path_job_proves_fail_fast_retry_and_timeout(self):
        workflow = yaml.safe_load(WORKFLOW.read_text())
        job = workflow["jobs"]["upl-01-error-paths"]
        self.assertEqual(job["needs"], "prepare-apk")
        dumped = yaml.safe_dump(job)
        self.assertIn("run-upl01-error-paths.sh", dumped)
        self.assertIn("upl01_error_path_server.py", dumped)
        self.assertIn("http://127.0.0.1:8787", dumped)
        self.assertIn("EXPO_PUBLIC_API_TIMEOUT_MS", dumped)

        runner = (FLOW_DIR / "run-upl01-error-paths.sh").read_text()
        self.assertIn('run_case 401 1 "API 401"', runner)
        self.assertIn('run_case 403 1 "API 403"', runner)
        self.assertIn('run_case 429 3 "API 429"', runner)
        self.assertIn('run_case 503 3 "API 503"', runner)
        self.assertIn('run_case timeout 3 "API timeout"', runner)
        self.assertIn('data["upload_requests"] == expected_count', runner)
        self.assertIn("pre-retry-server-evidence-attempt-$attempt.json", runner)
        self.assertIn('upload_requests" -ne 0', runner)
        self.assertIn("DeviceServerDiedException", runner)
        self.assertIn("for attempt in 1 2 3", runner)
        self.assertIn("retrying $scenario after proven emulator failure with zero upload requests", runner)
        self.assertIn("exhausted three infrastructure-only attempts", runner)
        self.assertIn("refusing retry for $scenario", runner)

        flow = (FLOW_DIR / "15-isolated-api-error.yaml").read_text()
        self.assertIn('id: "upload-item-status-failed"', flow)
        self.assertIn("EXPECTED_ERROR_REGEX", flow)

        summary = workflow["jobs"]["upl-01-summary"]
        self.assertIn("upl-01-error-paths", summary["needs"])

    def test_validation_timeout_override_never_enters_eas_profiles(self):
        eas = json.loads((ROOT / "mobile/eas.json").read_text())
        for profile, config in eas["build"].items():
            self.assertNotIn("EXPO_PUBLIC_API_TIMEOUT_MS", config.get("env", {}), profile)

    def test_validation_bypass_never_enters_an_eas_build_profile(self):
        eas = json.loads((ROOT / "mobile/eas.json").read_text())
        for profile, config in eas["build"].items():
            self.assertNotIn("EXPO_PUBLIC_UPL01_OPERATOR_BYPASS", config.get("env", {}), profile)
        allowed_runtime_workflows = {WORKFLOW.name, "full-android-app-qualification.yml"}
        for workflow in (ROOT / ".github/workflows").glob("*.yml"):
            if workflow.name not in allowed_runtime_workflows:
                self.assertNotIn("EXPO_PUBLIC_UPL01_OPERATOR_BYPASS", workflow.read_text(), workflow.name)

        full_android = yaml.safe_load((ROOT / ".github/workflows/full-android-app-qualification.yml").read_text())
        prepare_apk = full_android["jobs"]["prepare-apk"]
        self.assertNotIn(
            "EXPO_PUBLIC_UPL01_OPERATOR_BYPASS",
            yaml.safe_dump(prepare_apk),
            "validation bypass must stay out of APK build steps",
        )


if __name__ == "__main__":
    unittest.main(verbosity=1)
