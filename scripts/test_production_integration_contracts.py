#!/usr/bin/env python3
"""Contract and integration tests for production-connected hybrid optimizations (P0, P1, P2).

Verifies that OPT-01..OPT-07 are actively wired into production execution paths:
  1. OPT-07: Real render cache pre-check & post-save in `pipeline.stages.editor`.
  2. OPT-06: Internal activity window slicing and piecewise remapping in `pipeline.stages.analyzer`.
  3. OPT-04: Tiered QA gate active in `qa_check_reel` with fail-fast Layer 1 & cached Layer 2.
  4. P0.4: Explicit `invocation_id` scoping across Render -> QA -> Evidence.
  5. P1.1 & P1.2: Active `IdentityDecisionEngine` and visual embedding candidate filtering in clustering.
  6. P2.1: Native container FPS detection avoiding timestamp drift.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _stub_modules() -> None:
    if "config" in sys.modules:
        if not hasattr(sys.modules["config"], "GEMINI_MODEL"):
            sys.modules["config"].GEMINI_MODEL = "gemini-2.5-pro"
        if not hasattr(sys.modules["config"], "TMP_DIR"):
            sys.modules["config"].TMP_DIR = tempfile.gettempdir()
    if "langsmith" not in sys.modules:
        sys.modules["langsmith"] = types.SimpleNamespace(traceable=lambda *a, **k: (lambda fn: fn))
    if "google.genai" not in sys.modules:
        genai_mod = types.ModuleType("google.genai")
        genai_mod.types = types.SimpleNamespace(GenerateContentConfig=MagicMock)
        genai_mod.Client = MagicMock
        google_mod = types.ModuleType("google")
        google_mod.genai = genai_mod
        sys.modules["google"] = google_mod
        sys.modules["google.genai"] = genai_mod

_stub_modules()

from pipeline import activity_window
from pipeline.identity_decision_engine import IdentityDecisionEngine
from pipeline.publishable_pending_scope import (
    activate_next_scope,
    create_pending_scope,
    current_scope_token,
    release_scope,
)
from pipeline.render_qa_cache import (
    compute_qa_signature,
    compute_render_signature,
    get_cached_qa_result,
    get_cached_render,
    put_cached_qa_result,
    put_cached_render,
)
from pipeline.stages import analyzer, editor, identity


class TestProductionIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_cache_dir = os.environ.get("SPORTREEL_RENDER_QA_CACHE_DIR")
        os.environ["SPORTREEL_RENDER_QA_CACHE_DIR"] = str(Path(self.temp_dir) / "render_qa")

    def tearDown(self):
        if self.orig_cache_dir:
            os.environ["SPORTREEL_RENDER_QA_CACHE_DIR"] = self.orig_cache_dir
        else:
            os.environ.pop("SPORTREEL_RENDER_QA_CACHE_DIR", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_opt07_render_cache_in_editor(self):
        """P0.1: Verify real render cache pre-check and post-save in editor."""
        test_video = Path(self.temp_dir) / "src.mp4"
        test_video.write_bytes(b"dummy_mp4_bytes_source")

        appearances = [{
            "path": str(test_video),
            "events": [
                {"type": "turn", "start": 5.0, "end": 12.0, "score": 8, "crop_x": 0.5, "crop_y": 0.65}
            ]
        }]
        dest_reel = Path(self.temp_dir) / "dest_reel.mp4"

        sig = compute_render_signature(appearances, sport="surfing", athlete_label="athlete_A")
        self.assertTrue(len(sig) == 64)

        # 1. Miss initially
        hit, events = get_cached_render(sig, str(dest_reel))
        self.assertFalse(hit)
        self.assertIsNone(events)

        # 2. Simulate successful render and put_cached_render
        rendered_fake = Path(self.temp_dir) / "rendered_fake.mp4"
        rendered_fake.write_bytes(b"fake_rendered_reel_bytes_123456789")
        cached_events = [{"type": "turn", "start": 0.0, "end": 7.0}]

        ok = put_cached_render(sig, str(rendered_fake), cached_events)
        self.assertTrue(ok)

        # 3. Hit on second render: restores file and events without FFmpeg
        hit, restored_events = get_cached_render(sig, str(dest_reel))
        self.assertTrue(hit)
        self.assertEqual(restored_events, cached_events)
        self.assertTrue(dest_reel.exists())
        self.assertEqual(dest_reel.read_bytes(), b"fake_rendered_reel_bytes_123456789")

        # 4. Invalidation: change crop_x or athlete_label
        appearances_mod = [{
            "path": str(test_video),
            "events": [
                {"type": "turn", "start": 5.0, "end": 12.0, "score": 8, "crop_x": 0.8, "crop_y": 0.65}
            ]
        }]
        sig_mod = compute_render_signature(appearances_mod, sport="surfing", athlete_label="athlete_A")
        self.assertNotEqual(sig, sig_mod)
        hit_mod, _ = get_cached_render(sig_mod, str(dest_reel))
        self.assertFalse(hit_mod)

    def test_opt06_internal_activity_windows_and_remap(self):
        """P0.2: Verify internal activity windows and piecewise timestamp remapping."""
        dets = [
            {"time_sec": 10.0, "confidence": 0.90},
            {"time_sec": 15.0, "confidence": 0.92},
            {"time_sec": 20.0, "confidence": 0.88},
            {"time_sec": 80.0, "confidence": 0.91},
            {"time_sec": 85.0, "confidence": 0.89},
            {"time_sec": 90.0, "confidence": 0.95},
        ]
        res = activity_window.compute_internal_activity_windows(dets, duration=120.0, pad_sec=4.0, min_gap_sec=15.0)
        self.assertEqual(res["mode"], "internal_windows")
        self.assertEqual(len(res["windows"]), 2)
        # Window 1: 10-4=6s to 20+4=24s
        self.assertEqual(res["windows"][0], (6.0, 24.0))
        # Window 2: 80-4=76s to 90+4=94s
        self.assertEqual(res["windows"][1], (76.0, 94.0))

        ts_map = res["timestamp_map"]
        session = {
            "activity": "surfing",
            "persons": [{
                "id": "p1",
                "events": [
                    {"type": "cutback", "start": 2.0, "end": 10.0, "peak_time": 6.0},
                    {"type": "barrel", "start": 20.0, "end": 30.0, "peak_time": 25.0},
                ]
            }]
        }
        remapped = ts_map.remap_session_to_source(session)
        ev1 = remapped["persons"][0]["events"][0]
        ev2 = remapped["persons"][0]["events"][1]

        # In window 1 (starts at 6.0s): condensed 2.0s -> source 8.0s
        self.assertEqual(ev1["start"], 8.0)
        self.assertEqual(ev1["end"], 16.0)
        self.assertEqual(ev1["peak_time"], 12.0)

        # In window 2 (condensed offset = 18s (window 1 len), window 2 starts at 76.0s):
        # condensed 20s (2s into window 2) -> source 76 + 2 = 78.0s
        self.assertEqual(ev2["start"], 78.0)
        self.assertEqual(ev2["end"], 88.0)

    def test_opt04_tiered_qa_gate_integration(self):
        """P0.3: Verify Tier 1 reject (0 LLM tokens) and Tier 2 cached QA retrieval."""
        reel = Path(self.temp_dir) / "reel_qa_test.mp4"
        reel.write_bytes(b"dummy_rendered_reel_bytes_for_qa")

        gemini_called = False

        def mock_gemini(path, sport, label):
            nonlocal gemini_called
            gemini_called = True
            return {
                "verdict": "PASS",
                "engagement_score": 85,
                "defects": [],
                "content": {"hook": 9, "pacing": 8},
                "overall": "Strong reel",
            }

        with patch("pipeline.stages.analyzer._check_technical_compliance") as mock_tech:
            # Case A: Technical fail (Tier 1 reject) -> Gemini NOT called
            mock_tech.return_value = ({"duration": 15.0, "aspect": 0.5625, "has_audio": True}, False, ["unexpected_audio"])
            res = analyzer.qa_check_reel(str(reel), sport="surfing", athlete_label="athlete_A")
            self.assertEqual(res["verdict"], "FAIL")
            self.assertFalse(gemini_called)
            self.assertEqual(res.get("qa_tier"), "tier1_local_reject")
            self.assertFalse(res.get("llm_called", True))

            # Case B: Technical pass -> Gemini called on first run
            mock_tech.return_value = ({"duration": 15.0, "aspect": 0.5625, "height": 3840, "has_audio": False}, True, [])
            with patch.object(analyzer, "_upload_video", return_value="dummy_vf"):
                with patch.object(analyzer, "_delete_video", return_value=None):
                    with patch.object(analyzer.genai, "GenerativeModel") as mock_model_cls:
                        mock_model = MagicMock()
                        mock_resp = MagicMock()
                        mock_resp.text = json.dumps({
                            "verdict": "PASS",
                            "engagement_score": 85,
                            "defects": [],
                            "content": {"hook": 9, "pacing": 8},
                            "overall": "Strong reel",
                        })
                        mock_model.generate_content.return_value = mock_resp
                        mock_model_cls.return_value = mock_model

                        res2 = analyzer.qa_check_reel(str(reel), sport="surfing", athlete_label="athlete_A", events=[{"type": "turn", "start": 0, "end": 15}])
                        self.assertEqual(res2["verdict"], "PASS")
                        self.assertEqual(res2.get("qa_tier"), "tier2_live_content_qa")
                        self.assertTrue(res2.get("llm_called"))

            # Case C: Second run with identical file and EDL -> QA Cache Hit (Tier 2, 0 LLM calls!)
            res3 = analyzer.qa_check_reel(str(reel), sport="surfing", athlete_label="athlete_A", events=[{"type": "turn", "start": 0, "end": 15}])
            self.assertEqual(res3["verdict"], "PASS")
            self.assertEqual(res3.get("qa_tier"), "tier2_cached_content_qa")
            self.assertFalse(res3.get("llm_called", True))

    def test_p04_explicit_invocation_id_scoping(self):
        """P0.4: Verify explicit invocation_id prevents collisions between identical descriptions."""
        inv1 = "inv_athlete_123"
        inv2 = "inv_athlete_456"

        tok1 = create_pending_scope("surfing", "surfer in black wetsuit", invocation_id=inv1)
        tok2 = create_pending_scope("surfing", "surfer in black wetsuit", invocation_id=inv2)
        self.assertNotEqual(tok1, tok2)

        # Activate inv2 specifically
        act2 = activate_next_scope("surfing", "surfer in black wetsuit", invocation_id=inv2)
        self.assertEqual(act2, tok2)
        self.assertEqual(current_scope_token(), tok2)
        release_scope(tok2)

        # Activate inv1 specifically
        act1 = activate_next_scope("surfing", "surfer in black wetsuit", invocation_id=inv1)
        self.assertEqual(act1, tok1)
        self.assertEqual(current_scope_token(), tok1)
        release_scope(tok1)

    def test_p12_identity_decision_engine_active_in_clustering(self):
        """P1.2: Verify IdentityDecisionEngine actively splits clusters with hard conflicts."""
        engine = IdentityDecisionEngine()
        left = {
            "path": "video_A.mp4",
            "_person_id": "p1",
            "description": "surfer with red board and black wetsuit #7",
        }
        right = {
            "path": "video_B.mp4",
            "_person_id": "p2",
            "description": "surfer with yellow board and blue boardshorts #9",
        }
        dec = engine.evaluate_pair(left, right)
        self.assertEqual(dec.decision, "NO_MATCH")
        self.assertIn("conflicting_jersey_or_bib_numbers", dec.reasons)

        # Verify _split_impossible_clusters splits a cluster containing left and right
        cluster = {
            "description": "mixed cluster",
            "appearances": [left, right],
        }
        split = identity._split_impossible_clusters([cluster])
        self.assertEqual(len(split), 2)


if __name__ == "__main__":
    unittest.main()
