import importlib
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch


class RenderQualityTests(unittest.TestCase):
    def setUp(self):
        self.config_stub = types.SimpleNamespace(
            REEL_FULL_HD_MIN_SOURCE_HEIGHT=1440,
            REEL_WARN_UPSCALE_FACTOR=1.25,
            MIN_SOURCE_HEIGHT=1440,
        )
        sys.modules["config"] = self.config_stub
        sys.modules.pop("integrations.ffmpeg", None)
        self.ffmpeg = importlib.import_module("integrations.ffmpeg")

    def _mock_probe(self, width, height, fps="30/1"):
        return Mock(stdout=json.dumps({
            "streams": [{
                "width": width,
                "height": height,
                "r_frame_rate": fps,
            }]
        }))

    def test_1080p_landscape_is_flagged_as_upscale_risk(self):
        with patch("integrations.ffmpeg.subprocess.run", return_value=self._mock_probe(1920, 1080)):
            info = self.ffmpeg.get_source_info("source_1080p.mp4")

        self.assertEqual(info["render_quality_tier"], "upscale_risk")
        self.assertEqual(info["recommended_reel_width"], 720)
        self.assertEqual(info["recommended_reel_height"], 1280)
        self.assertAlmostEqual(info["portrait_upscale_1080"], 1.78, places=2)
        self.assertLess(info["zoom_headroom"], 1.15)
        self.assertTrue(any("1080x1920" in warning for warning in info["quality_warnings"]))

    def test_4k_landscape_has_no_forced_portrait_upscale(self):
        with patch("integrations.ffmpeg.subprocess.run", return_value=self._mock_probe(3840, 2160, "60/1")):
            info = self.ffmpeg.get_source_info("source_4k.mp4")

        self.assertEqual(info["render_quality_tier"], "4k_safe")
        self.assertEqual(info["recommended_reel_width"], 1080)
        self.assertEqual(info["recommended_reel_height"], 1920)
        self.assertEqual(info["portrait_upscale_1080"], 1.0)
        self.assertTrue(info["can_slowmo"])


if __name__ == "__main__":
    unittest.main()
