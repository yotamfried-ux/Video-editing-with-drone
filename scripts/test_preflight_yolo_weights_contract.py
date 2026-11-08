#!/usr/bin/env python3
"""Offline contract regressions for pinned YOLO model preflight."""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import preflight_yolo_weights as w


class TestYoloAssetPreflight(unittest.TestCase):
    def test_producer_command_override_wins_over_workflow_default(self):
        self.assertEqual(w.effective_model(
            "python scripts/generate_perception_sidecar.py {video_path} {sidecar_path} --backend ultralytics "
            "--ultralytics-model yolo11n.pt", "yolo11s.pt"), "yolo11n.pt")
        self.assertEqual(w.effective_model("--ultralytics-model=yolo11n.pt", "yolo11s.pt"), "yolo11n.pt")
        self.assertEqual(w.effective_model("", "yolo11s.pt"), "yolo11s.pt")

    def test_cached_weight_must_have_exact_sha256_not_just_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "yolo11n.pt"
            good = b"verified-placeholder" * 10000
            file.write_bytes(good)
            checksum = hashlib.sha256(good).hexdigest()
            self.assertTrue(w.is_verified(file, checksum))
            file.write_bytes(good[:-1] + b"x")
            self.assertFalse(w.is_verified(file, checksum))

    def test_verified_cache_avoids_network_and_concurrent_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "yolo11n.pt"
            blob = b"offline-fixture" * 10000
            file.write_bytes(blob)
            digest = hashlib.sha256(blob).hexdigest()
            with patch.dict(w._ASSETS, {"yolo11n.pt": digest}), patch.object(w, "urlopen", side_effect=AssertionError("network called")):
                self.assertEqual(w.ensure_official_weight("yolo11n.pt", root), file)


if __name__ == "__main__":
    unittest.main()
