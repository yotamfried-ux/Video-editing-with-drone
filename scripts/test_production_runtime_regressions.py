#!/usr/bin/env python3
"""Regression tests for real production timing, scope isolation and render cache validity."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ProductionIntegrityRegressions(unittest.TestCase):
    def test_window_concat_matches_piecewise_timestamps(self):
        from pipeline.activity_window import PiecewiseTimestampMap, create_analysis_window_video
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not available")
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source.mp4"
            output = Path(d) / "activity.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                "-i", "testsrc2=size=160x90:rate=10", "-t", "6",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)
            ], check=True, capture_output=True, timeout=60)
            windows = [(0.0, 1.0), (4.0, 5.0)]
            create_analysis_window_video(str(source), windows, str(output))
            self.assertTrue(output.exists())
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "json", str(output)
            ], check=True, capture_output=True, text=True, timeout=20)
            duration = float(json.loads(probe.stdout)["format"]["duration"])
            self.assertAlmostEqual(duration, 2.0, delta=0.3)
            timeline = PiecewiseTimestampMap(tuple(windows))
            self.assertAlmostEqual(timeline.condensed_to_source(1.4), 4.4, places=2)

    def test_explicit_scope_cannot_leave_stale_label_tokens(self):
        from pipeline.publishable_pending_scope import (
            create_pending_scope, activate_next_scope, release_scope
        )
        a = create_pending_scope("surfing", "same description", invocation_id="scope-a")
        b = create_pending_scope("surfing", "same description", invocation_id="scope-b")
        self.assertEqual(activate_next_scope("surfing", "same description", invocation_id="scope-b"), b)
        release_scope(b)
        self.assertEqual(activate_next_scope("surfing", "same description", invocation_id="scope-a"), a)
        release_scope(a)
        with self.assertRaises(RuntimeError):
            activate_next_scope("surfing", "same description")

    def test_exact_render_scope_metadata_survives_cross_thread_handoff(self):
        from concurrent.futures import ThreadPoolExecutor
        from pipeline.publishable_pending_scope import pending_key, activate_next_scope, release_scope
        from pipeline.publishable_reel_policy import _stamp_render_invocation
        from pipeline.context_qa_gate import _annotate_subject_gates

        label = "same surfer description"
        tok1 = pending_key("surfing", label)
        tok2 = pending_key("surfing", label)
        first = _stamp_render_invocation([
            ("reel1.mp4", [{"event_id": "e1", "_src": "raw_one.mp4", "start": 0, "end": 4}])
        ], tok1)
        second = _stamp_render_invocation([
            ("reel2.mp4", [{"event_id": "e2", "_src": "raw_two.mp4", "start": 0, "end": 4}])
        ], tok2)
        id1 = _annotate_subject_gates(first[0][1], "", label)[0]["_render_invocation_id"]
        id2 = _annotate_subject_gates(second[0][1], "", label)[0]["_render_invocation_id"]
        self.assertNotEqual(id1, id2)

        def activate(inv_id):
            token = activate_next_scope("surfing", label, invocation_id=inv_id)
            release_scope(token)
            return token

        with ThreadPoolExecutor(max_workers=2) as workers:
            # Reversed completion order must not swap scopes.
            result2 = workers.submit(activate, id2)
            result1 = workers.submit(activate, id1)
            self.assertEqual(result2.result(), tok2)
            self.assertEqual(result1.result(), tok1)

    def test_invalid_cached_media_never_accepted_by_editor(self):
        from pipeline.stages.editor import _valid_cached_reel
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "not_a_video.mp4"
            fake.write_bytes(b"not even an MP4")
            self.assertFalse(_valid_cached_reel(str(fake), 30))

    def test_teaser_affects_render_cache_signature(self):
        from pipeline.render_qa_cache import compute_render_signature
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source.mp4"
            source.write_bytes(b"source data")
            original = [
                {"path": str(source), "events": [
                    {"_teaser": True, "type": "turn", "start": 2.0, "end": 4.5},
                    {"type": "turn", "start": 20.0, "end": 30.0}
                ]}
            ]
            changed = [
                {"path": str(source), "events": [
                    {"_teaser": True, "type": "turn", "start": 6.0, "end": 8.5},
                    {"type": "turn", "start": 20.0, "end": 30.0}
                ]}
            ]
            self.assertNotEqual(
                compute_render_signature(original, sport="surfing"),
                compute_render_signature(changed, sport="surfing")
            )


if __name__ == "__main__":
    unittest.main()
