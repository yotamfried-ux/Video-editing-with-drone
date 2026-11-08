#!/usr/bin/env python3
"""Verify effective production 4K/30 encoder preset, not just editor.py defaults."""
from __future__ import annotations
import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class VerifiedPresetContract(unittest.TestCase):
    def test_quality_first_pipeline_defaults_to_veryfast(self):
        import pipeline.quality_preserving_framing as policy
        import pipeline.stages.editor as editor
        previous = os.environ.pop("X264_PRESET", None)
        try:
            importlib.reload(policy)
            self.assertEqual(policy.RENDER_X264_PRESET, "veryfast")
            policy.install()
            self.assertEqual(editor.X264_PRESET, "veryfast")
            self.assertEqual((editor.REEL_W, editor.REEL_H), (2160, 3840))
            self.assertEqual((editor.CLIP_CRF, editor.REEL_CRF), ("12", "14"))
        finally:
            if previous is not None:
                os.environ["X264_PRESET"] = previous
            importlib.reload(policy)


if __name__ == "__main__":
    unittest.main()
