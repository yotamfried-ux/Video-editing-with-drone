import unittest

from pipeline.stages import surf_editor


class SurfEditorPolicyTests(unittest.TestCase):
    def test_order_uses_short_high_impact_hook_and_best_climax(self):
        events = [
            {"type": "wave_catch", "start": 0, "end": 14, "score": 9, "edit": {"transition_out": "fade"}},
            {"type": "snap", "start": 20, "end": 27, "score": 8, "edit": {"transition_out": "slide"}},
            {"type": "barrel", "start": 40, "end": 50, "score": 10, "edit": {"transition_out": "zoom"}},
            {"type": "paddle", "start": 60, "end": 67, "score": 7, "edit": {"slowmo": True}},
        ]

        ordered = surf_editor.order_surf_events(events)

        self.assertEqual(ordered[0]["type"], "snap")
        self.assertEqual(ordered[-1]["type"], "barrel")
        self.assertEqual(ordered[0]["edit"]["transition_out"], "cut")
        paddle = next(event for event in ordered if event["type"] == "paddle")
        self.assertFalse(paddle["edit"].get("slowmo"))

    def test_refine_teaser_to_short_hook(self):
        event = {
            "type": "snap",
            "start": 10.0,
            "end": 12.5,
            "score": 9,
            "crop_x": 0.5,
            "_teaser": True,
            "edit": {"zoom": 1.4},
        }

        refined = surf_editor.refine_surf_event_window(event)

        self.assertAlmostEqual(refined["end"] - refined["start"], 1.6, places=2)
        self.assertEqual(event["start"], 10.0)  # no source mutation

    def test_edge_crop_limits_zoom_without_tracking(self):
        event = {
            "type": "cutback",
            "start": 10.0,
            "end": 20.0,
            "score": 8,
            "crop_x": 0.92,
            "edit": {"zoom": 1.7, "focus": "peak"},
        }

        refined = surf_editor.refine_surf_event_window(event)

        self.assertLessEqual(refined["edit"]["zoom"], 1.15)
        self.assertEqual(refined["edit"]["focus"], "full")

    def test_start_important_wave_catch_keeps_start_when_capped(self):
        event = {
            "type": "wave_catch",
            "start": 30.0,
            "end": 45.0,
            "score": 8,
            "crop_x": 0.5,
            "edit": {},
        }

        refined = surf_editor.refine_surf_event_window(event)

        self.assertEqual(refined["start"], 30.0)
        self.assertAlmostEqual(refined["end"], 37.5)


if __name__ == "__main__":
    unittest.main()
