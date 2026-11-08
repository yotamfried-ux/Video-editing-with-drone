#!/usr/bin/env python3
"""Comprehensive test matrix for P0-02: Perception Zero-Detection Handling & Recovery."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "ultralytics" not in sys.modules:
    ultra_mod = types.ModuleType("ultralytics")
    ultra_mod.YOLO = MagicMock
    sys.modules["ultralytics"] = ultra_mod

import pipeline.perception.runtime as rt
import pipeline.required_perception_policy as req_policy
from scripts.generate_perception_sidecar import _fast_ultralytics_sidecar


class TestP002ZeroDetectionMatrix(unittest.TestCase):
    def setUp(self):
        req_policy.install()

    def test_01_reusable_distinction(self):
        # Normal detection
        self.assertTrue(rt._is_reusable_sidecar({"status": "ok", "detection_count": 15}))
        # Unverified zero -> False
        self.assertFalse(rt._is_reusable_sidecar({"status": "ok", "detection_count": 0}))
        # Verified empty scene -> True
        self.assertTrue(rt._is_reusable_sidecar({
            "status": "ok",
            "detection_count": 0,
            "classification": "empty_scene",
            "empty_scene_verified": True,
        }))
        # Corrupted / technical failure -> False
        self.assertFalse(rt._is_reusable_sidecar({
            "status": "failed",
            "detection_count": 0,
            "technical_failure": True,
        }))

    def test_02_empty_scene_enrichment_does_not_crash_pipeline(self):
        empty_session = {"persons": []}
        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "empty_wave.mp4")
            sidecar_path = os.path.join(tmp, "empty_wave.mp4.perception.json")
            payload = {
                "source_video": video_path,
                "status": "ok",
                "classification": "empty_scene",
                "empty_scene_verified": True,
                "reason": "no_person_detected_after_dense_scan",
                "detections": [],
                "raw_person_boxes": 0,
            }
            with open(sidecar_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)

            enriched = rt.enrich_session_with_sidecar(empty_session, video_path)
            self.assertEqual(enriched.get("persons"), [])
            self.assertEqual(enriched.get("perception_evidence_status"), "empty_scene")

    def test_unconfirmed_zero_detection_preserves_audit_and_prevents_false_empty(self):
        from pipeline.perception.runtime import enrich_session_with_sidecar
        from pipeline.required_perception_policy import install as install_required
        from pipeline.perception.runtime import sidecar_output_path
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "missed_surfer.mp4"
            source.write_bytes(b"synthetic source placeholder")
            sidecar = sidecar_output_path(str(source))
            sidecar.write_text(json.dumps({
                "source_video": str(source),
                "status": "ok",
                "classification": "review_required",
                "empty_scene_verified": False,
                "reason": "zero_person_detections_unverified",
                "detections": []
            }), encoding="utf-8")
            install_required()
            session = {"persons": [{"id": "p1", "events": [
                {"type": "surf_ride", "start": 1, "end": 3}
            ]}]}
            result = enrich_session_with_sidecar(session, str(source))
            self.assertFalse(result.get("empty_scene_verified", False))
            self.assertEqual(result.get("perception_evidence_status"), "review_required")
            self.assertEqual(result["persons"][0].get("no_output_reason"), "perception_zero_detection_unverified")

    @patch("cv2.VideoCapture")
    def test_03_corrupt_video_fails_as_technical_failure(self, mock_vc):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False  # cannot open/read
        mock_vc.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "corrupt.mp4")
            Path(video_path).write_bytes(b"corrupted bytes")
            out_sidecar = os.path.join(tmp, "corrupt.perception.json")

            args = MagicMock()
            args.video_path = video_path
            args.output_path = out_sidecar
            args.backend = "ultralytics"
            args.detections_json = None
            args.ultralytics_model = "yolo11s.pt"
            args.ultralytics_tracker = "botsort.yaml"
            args.ultralytics_vid_stride = "10"
            args.ultralytics_imgsz = "640"
            args.ultralytics_device = "cpu"
            args.fps = "30"

            with patch("ultralytics.YOLO") as mock_yolo:
                mock_model = MagicMock()
                mock_model.track.return_value = []
                mock_yolo.return_value = mock_model
                payload = _fast_ultralytics_sidecar(args)

            self.assertEqual(payload["status"], "failed")
            self.assertTrue(payload.get("technical_failure"))
            self.assertIn("corrupt_video", payload.get("reason", ""))

    @patch("cv2.VideoCapture")
    def test_04_small_distant_athlete_rescued_by_dense_escalation(self, mock_vc):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, MagicMock())
        mock_cap.get.return_value = 300  # 300 frames
        mock_vc.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "far_surfer.mp4")
            Path(video_path).write_bytes(b"dummy video")
            out_sidecar = os.path.join(tmp, "far_surfer.perception.json")

            args = MagicMock()
            args.video_path = video_path
            args.output_path = out_sidecar
            args.backend = "ultralytics"
            args.detections_json = None
            args.ultralytics_model = "yolo11s.pt"
            args.ultralytics_tracker = "botsort.yaml"
            args.ultralytics_vid_stride = "10"
            args.ultralytics_imgsz = "640"
            args.ultralytics_device = "cpu"
            args.fps = "30"

            # Pass 1: 0 detections
            # Escalation pass: rescued small surfer
            rescued_detection = [{
                "frame_index": 45,
                "time_sec": 1.5,
                "bbox_xyxy": [400, 300, 440, 360],
                "confidence": 0.45,
                "class_id": 0,
                "class_name": "person",
                "track_id": 1,
            }]

            with patch("ultralytics.YOLO") as mock_yolo:
                mock_model = MagicMock()
                mock_model.track.return_value = []
                mock_yolo.return_value = mock_model
                with patch("scripts.generate_perception_sidecar._run_targeted_window_escalation", return_value=(rescued_detection, 10)):
                    payload = _fast_ultralytics_sidecar(args)

            self.assertEqual(payload["status"], "ok")
            self.assertEqual(len(payload["detections"]), 1)
            self.assertTrue(payload["adaptive_inference"].get("zero_detection_rescue"))
            self.assertEqual(payload["adaptive_inference"].get("rescued_detections_count"), 1)

    @patch("cv2.VideoCapture")
    def test_05_verified_empty_scene_when_dense_scan_also_zero(self, mock_vc):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.read.return_value = (True, MagicMock())
        mock_cap.get.return_value = 300
        mock_vc.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            video_path = os.path.join(tmp, "empty_sea.mp4")
            Path(video_path).write_bytes(b"dummy video")
            out_sidecar = os.path.join(tmp, "empty_sea.perception.json")

            args = MagicMock()
            args.video_path = video_path
            args.output_path = out_sidecar
            args.backend = "ultralytics"
            args.detections_json = None
            args.ultralytics_model = "yolo11s.pt"
            args.ultralytics_tracker = "botsort.yaml"
            args.ultralytics_vid_stride = "10"
            args.ultralytics_imgsz = "640"
            args.ultralytics_device = "cpu"
            args.fps = "30"

            with patch("ultralytics.YOLO") as mock_yolo:
                mock_model = MagicMock()
                mock_model.track.return_value = []
                mock_yolo.return_value = mock_model
                with patch("scripts.generate_perception_sidecar._run_targeted_window_escalation", return_value=([], 15)):
                    payload = _fast_ultralytics_sidecar(args)

            self.assertEqual(payload["status"], "ok")
            # Zero YOLO detections only proves a detector miss, NOT an empty ocean.
            self.assertFalse(payload.get("empty_scene_verified"))
            self.assertEqual(payload.get("classification"), "review_required")
            self.assertEqual(len(payload["detections"]), 0)
            self.assertEqual(payload.get("reason"), "zero_person_detections_unverified")


if __name__ == "__main__":
    unittest.main()
