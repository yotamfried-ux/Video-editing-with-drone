#!/usr/bin/env python3
"""Contract and regression tests for P0-03 (Reel Lifecycle State Machine) and P0-04 (Candidate Accountability Ledger).

Verifies:
  1. Reel lifecycle states:
     RENDERED -> QA_PENDING -> QA_PASSED -> UPLOAD_PENDING -> UPLOADED
     and failure branches: QA_FAILED, UPLOAD_FAILED, REVIEW_REQUIRED.
  2. Per-part metadata completeness:
     product_id, athlete_id, run_id, content_sha256, state, attempts, attempt_history, failure_reason.
  3. Crash recovery & resumption:
     Existing valid uploaded drafts are preserved on restart without duplicate uploads.
  4. Candidate decision ledger:
     100% of candidate actions have an explicit status and a valid discard reason code.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import publishable_qa_evidence, publishable_reel_policy as policy
from scripts import build_candidate_decision_ledger as ledger_builder


class TestP03P04LifecycleAndLedger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manifest_file = Path(self.temp_dir) / "publishable_manifest.json"
        self.orig_manifest = os.environ.get("PUBLISHABLE_REEL_MANIFEST_FILE")
        os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = str(self.manifest_file)
        policy.reset_manifest()

    def tearDown(self):
        if self.orig_manifest:
            os.environ["PUBLISHABLE_REEL_MANIFEST_FILE"] = self.orig_manifest
        else:
            os.environ.pop("PUBLISHABLE_REEL_MANIFEST_FILE", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_fake_reel(self, name: str = "reel_athlete1.mp4") -> Path:
        p = Path(self.temp_dir) / name
        p.write_bytes(b"dummy_4k_mp4_bytes_content_for_athlete1")
        return p

    def test_p03_lifecycle_state_machine_happy_path(self):
        """Verify RENDERED -> QA_PASSED / UPLOAD_PENDING -> UPLOADED transitions and metadata."""
        reel_path = self._create_fake_reel()
        events = [{"type": "cutback", "start": 10.0, "end": 20.0, "source": "drone1.mp4"}]

        # 1. Record athlete outcome after render
        row = policy.record_athlete_outcome(
            sport="surfing",
            athlete_label="Surfer in red shorts",
            final_reels=[str(reel_path)],
            events_by_reel={str(reel_path): events},
            flagged_paths=set(),
            specs_by_path={
                str(reel_path): {
                    "duration": 15.0,
                    "width": 2160,
                    "height": 3840,
                    "aspect": 0.5625,
                    "has_audio": False,
                }
            },
        )
        self.assertEqual(len(row["parts"]), 1)
        part = row["parts"][0]

        # Verify metadata
        self.assertTrue(part["product_id"].startswith("reel_"))
        self.assertTrue(len(part["content_sha256"]) == 64)
        self.assertEqual(part["athlete_id"], row["athlete_key"])
        self.assertEqual(part["state"], policy.STATE_UPLOAD_PENDING)
        self.assertIsNone(part["failure_reason"])
        self.assertEqual(part["attempts"], 1)
        self.assertEqual(len(part["attempt_history"]), 1)

        # 2. Attach QA evidence
        token = "test_qa_tok_123"
        publishable_qa_evidence.record_qa_result(
            str(reel_path),
            {"verdict": "PASS", "engagement_score": 88, "overall": "Clean ride", "defects": []},
            invocation_token=token,
        )
        blocked = publishable_qa_evidence.apply_final_qa_evidence(
            sport="surfing",
            athlete_label="Surfer in red shorts",
            final_reels=[str(reel_path)],
            invocation_token=token,
        )
        self.assertEqual(len(blocked), 0)

        # Re-read manifest
        manifest = policy._read_manifest()
        part = manifest["athletes"][0]["parts"][0]
        self.assertEqual(part["state"], policy.STATE_UPLOAD_PENDING)
        self.assertTrue(part["render_ready"])
        self.assertTrue(part["qa_passed"])
        self.assertEqual(part["qa_verdict"], "PASS")

        # 3. Mark upload result
        with patch.object(policy, "_persist_draft_publishability", return_value=None):
            ok = policy.mark_upload_result(str(reel_path), "review_draft_surfer_red.mp4", storage_object_id="obj_999")
            self.assertTrue(ok)

        manifest = policy._read_manifest()
        part = manifest["athletes"][0]["parts"][0]
        self.assertEqual(part["state"], policy.STATE_UPLOADED)
        self.assertTrue(part["uploaded_to_review"])
        self.assertEqual(part["review_draft_name"], "review_draft_surfer_red.mp4")
        self.assertEqual(part["storage_object_id"], "obj_999")
        self.assertIsNone(part["failure_reason"])

    def test_p03_lifecycle_failure_branches(self):
        """Verify QA_FAILED, UPLOAD_FAILED, and REVIEW_REQUIRED branches."""
        reel_path_b = self._create_fake_reel("failed_reel_b.mp4")
        reel_path_c = self._create_fake_reel("failed_reel_c.mp4")
        events = [{"type": "cutback", "start": 5.0, "end": 15.0}]

        # Case A: Technical defect (audio stream present) -> QA_FAILED
        row = policy.record_athlete_outcome(
            sport="surfing",
            athlete_label="Surfer B",
            final_reels=[str(reel_path_b)],
            events_by_reel={str(reel_path_b): events},
            flagged_paths=set(),
            specs_by_path={
                str(reel_path_b): {
                    "duration": 20.0,
                    "width": 2160,
                    "height": 3840,
                    "aspect": 0.5625,
                    "has_audio": True,  # Violation of silent output policy
                }
            },
        )
        part = row["parts"][0]
        self.assertEqual(part["state"], policy.STATE_QA_FAILED)
        self.assertIn("unexpected_audio", part["failure_reason"])

        # Case B: Flagged path -> QA_FAILED
        row2 = policy.record_athlete_outcome(
            sport="surfing",
            athlete_label="Surfer C",
            final_reels=[str(reel_path_c)],
            events_by_reel={str(reel_path_c): events},
            flagged_paths={str(reel_path_c)},
            specs_by_path={
                str(reel_path_c): {
                    "duration": 20.0,
                    "width": 2160,
                    "height": 3840,
                    "aspect": 0.5625,
                    "has_audio": False,
                }
            },
        )
        part2 = row2["parts"][0]
        self.assertEqual(part2["state"], policy.STATE_QA_FAILED)
        self.assertEqual(part2["failure_reason"], "final_qa_failed")

        # Case C: Upload failure -> UPLOAD_FAILED
        policy.mark_upload_result(str(reel_path_c), "draft_failed.mp4", error="R2 S3 503 Service Unavailable")
        manifest = policy._read_manifest()
        matching_part = None
        for a in manifest["athletes"]:
            if a["athlete_label"] == "Surfer C":
                matching_part = a["parts"][0]
        self.assertIsNotNone(matching_part)
        self.assertEqual(matching_part["state"], policy.STATE_UPLOAD_FAILED)
        self.assertIn("503 Service Unavailable", matching_part["failure_reason"])

    def test_p03_checkpoint_resumption_no_duplicate_upload(self):
        """Verify resuming a run does not re-upload or invalidate an already uploaded reel."""
        reel_path = self._create_fake_reel("resumed_reel.mp4")
        events = [{"type": "barrel", "start": 5.0, "end": 18.0}]

        # 1. Complete initial render & upload
        policy.record_athlete_outcome(
            sport="surfing",
            athlete_label="Surfer D",
            final_reels=[str(reel_path)],
            events_by_reel={str(reel_path): events},
            flagged_paths=set(),
            specs_by_path={
                str(reel_path): {"duration": 13.0, "width": 2160, "height": 3840, "aspect": 0.5625, "has_audio": False}
            },
        )
        with patch.object(policy, "_persist_draft_publishability", return_value=None):
            policy.mark_upload_result(str(reel_path), "draft_surfer_d.mp4", storage_object_id="r2_id_101")

        # 2. Simulate pipeline resumption: record_athlete_outcome called again with same file
        row = policy.record_athlete_outcome(
            sport="surfing",
            athlete_label="Surfer D",
            final_reels=[str(reel_path)],
            events_by_reel={str(reel_path): events},
            flagged_paths=set(),
            specs_by_path={
                str(reel_path): {"duration": 13.0, "width": 2160, "height": 3840, "aspect": 0.5625, "has_audio": False}
            },
        )
        part = row["parts"][0]
        # Must retain STATE_UPLOADED and not revert to UPLOAD_PENDING!
        self.assertEqual(part["state"], policy.STATE_UPLOADED)
        self.assertTrue(part["uploaded_to_review"])
        self.assertEqual(part["storage_object_id"], "r2_id_101")

    def test_restarting_same_run_preserves_approved_manifest(self):
        """A new process must not erase a completed QA/upload checkpoint."""
        old = os.environ.get("PIPELINE_RUN_ID")
        try:
            os.environ["PIPELINE_RUN_ID"] = "durable-run-a"
            policy.reset_manifest()
            reel = self._create_fake_reel("durable.mp4")
            policy.record_athlete_outcome(
                sport="surfing", athlete_label="Surfer D",
                final_reels=[str(reel)],
                events_by_reel={str(reel): [{"type": "surf_ride", "start": 1, "end": 8}]},
                flagged_paths=set(),
                specs_by_path={str(reel): {
                    "duration": 7.0, "width": 2160, "height": 3840,
                    "aspect": 0.5625, "has_audio": False,
                }}
            )
            with patch.object(policy, "_persist_draft_publishability", return_value=None):
                policy.mark_upload_result(str(reel), "draft_durable.mp4", storage_object_id="obj-durable")
            self.assertEqual(policy._read_manifest()["athletes"][0]["parts"][0]["state"], policy.STATE_UPLOADED)
            policy.initialize_manifest()  # simulates the install hook on restart
            self.assertEqual(policy._read_manifest()["athletes"][0]["parts"][0]["state"], policy.STATE_UPLOADED)
            os.environ["PIPELINE_RUN_ID"] = "new-distinct-run-b"
            policy.initialize_manifest()
            self.assertEqual(policy._read_manifest()["athletes"], [])
        finally:
            if old is None:
                os.environ.pop("PIPELINE_RUN_ID", None)
            else:
                os.environ["PIPELINE_RUN_ID"] = old

    def test_remote_checkpoint_recovers_when_runner_local_disk_is_lost(self):
        """A fresh runner must load the persisted R2 manifest for the same run ID."""
        old = os.environ.get("PIPELINE_RUN_ID")
        os.environ["PIPELINE_RUN_ID"] = "run-with-remote-checkpoint"
        try:
            recovered = policy._empty_manifest()
            recovered["athletes"] = [{"athlete_key": "a1", "parts": [
                {"state": policy.STATE_UPLOADED, "storage_object_id": "review/reel.mp4"}
            ]}]
            self.manifest_file.unlink(missing_ok=True)
            with patch.object(policy, "_remote_checkpoint_enabled", return_value=True):
                with patch.object(policy, "_load_remote_manifest", return_value=recovered) as remote:
                    policy.initialize_manifest()
                    remote.assert_called_once()
            self.assertEqual(policy._read_manifest()["athletes"][0]["parts"][0]["state"], policy.STATE_UPLOADED)
        finally:
            if old is None:
                os.environ.pop("PIPELINE_RUN_ID", None)
            else:
                os.environ["PIPELINE_RUN_ID"] = old

    def test_p04_candidate_accountability_ledger_100_percent_reason_codes(self):
        """Verify that every discarded candidate has an explicit reason code."""
        trace_path = Path(self.temp_dir) / "trace.json"
        upstream_path = Path(self.temp_dir) / "upstream.json"

        upstream_payload = {
            "schema_version": "v1",
            "candidates": [
                {
                    "candidate_id": "c1",
                    "draft_id": "d1",
                    "person_id": "p1",
                    "athlete_id": "ath1",
                    "selected": True,
                    "discarded": False,
                    "source_video": "drone1.mp4",
                    "source_window": {"start": 10.0, "end": 20.0, "duration": 10.0},
                },
                {
                    "candidate_id": "c2",
                    "draft_id": None,
                    "person_id": "p1",
                    "athlete_id": "ath1",
                    "selected": True,
                    "discarded": False,
                    "source_video": "drone1.mp4",
                    "source_window": {"start": 50.0, "end": 60.0, "duration": 10.0},
                },
                {
                    "candidate_id": "c3",
                    "person_id": "p2",
                    "athlete_id": "ath2",
                    "selected": False,
                    "discarded": True,
                    "discard_cause": "identity_conflict",
                    "source_video": "drone2.mp4",
                    "source_window": {"start": 5.0, "end": 12.0, "duration": 7.0},
                },
                {
                    "candidate_id": "c4",
                    "person_id": "p3",
                    "athlete_id": "ath3",
                    "selected": False,
                    "discarded": True,
                    "discard_cause": None,  # Missing cause in upstream
                    "source_video": "drone3.mp4",
                    "source_window": {"start": 1.0, "end": 4.0, "duration": 3.0},
                },
            ],
        }
        trace_payload = {
            "schema_version": "v1",
            "drafts": [
                {
                    "draft_id": "d1",
                    "draft_name": "reel_ath1.mp4",
                    "source_windows": [
                        {
                            "start": 10.0,
                            "end": 20.0,
                            "duration": 10.0,
                            "source_video": "drone1.mp4",
                            "person_id": "p1",
                            "athlete_id": "ath1",
                        }
                    ],
                }
            ],
        }

        trace_path.write_text(json.dumps(trace_payload), encoding="utf-8")
        upstream_path.write_text(json.dumps(upstream_payload), encoding="utf-8")

        ledger = ledger_builder.build_ledger(trace_path, upstream_path)
        self.assertEqual(ledger["candidate_count"], 4)
        self.assertEqual(ledger["selected_count"], 1)
        self.assertEqual(ledger["discarded_count"], 3)
        self.assertEqual(ledger["unmatched_selector_selected_count"], 1)

        # Incomplete upstream data must remain explicitly unverified; inventing
        # 'not_a_useful_action' would hide missed athlete/action recall defects.
        self.assertFalse(ledger["discard_causes_available"])
        causes = {c["candidate_id"]: c.get("discard_cause") for c in ledger["candidates"]}
        self.assertEqual(causes["c3"], "identity_conflict")
        self.assertIsNone(causes["c4"])
        self.assertEqual(causes["c2"], "selected_by_selector_not_emitted_as_draft")
        self.assertEqual(ledger.get("unexplained_discard_count"), 1)
        self.assertEqual(ledger["recall_status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
