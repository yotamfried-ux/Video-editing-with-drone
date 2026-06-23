import importlib
import sys
import types
import unittest
from unittest.mock import patch


def _traceable(*_args, **_kwargs):
    def decorator(fn):
        return fn

    # Support both @traceable and @traceable(...)
    if _args and callable(_args[0]) and not _kwargs:
        return _args[0]
    return decorator


sys.modules.setdefault("langsmith", types.SimpleNamespace(traceable=_traceable))
sys.modules.setdefault("config", types.SimpleNamespace(GEMINI_MODEL="test-model"))
sys.modules.setdefault(
    "integrations.gemini",
    types.SimpleNamespace(
        genai=types.SimpleNamespace(
            upload_file=lambda *args, **kwargs: None,
            delete_file=lambda *args, **kwargs: None,
            GenerativeModel=lambda *args, **kwargs: None,
        )
    ),
)

identity = importlib.import_module("pipeline.stages.identity")


def _clip(path, persons):
    return {"path": path, "analysis": {"persons": persons}}


def _person(pid, description):
    return {
        "id": pid,
        "description": description,
        "events": [{"start": 1.0, "end": 8.0, "score": 8}],
    }


class IdentityClusteringTests(unittest.TestCase):
    def test_same_clip_conflict_is_split(self):
        clips = [
            _clip("clip0.mp4", [
                _person("person_A", "player #7 red shirt"),
                _person("person_B", "player #7 red shirt"),
            ])
        ]
        data = {
            "clusters": [{
                "description": "player #7 red shirt",
                "confidence": "high",
                "appearances": [
                    {"clip_index": 0, "person_id": "person_A"},
                    {"clip_index": 0, "person_id": "person_B"},
                ],
            }]
        }

        clusters = identity._build_clusters_from_data(data, clips)

        self.assertEqual(len(clusters), 2)
        self.assertTrue(all(len(c["appearances"]) == 1 for c in clusters))

    def test_low_confidence_multi_clip_cluster_is_split(self):
        clips = [
            _clip("clip0.mp4", [_person("person_A", "surfer in black wetsuit")]),
            _clip("clip1.mp4", [_person("person_A", "surfer in black wetsuit")]),
        ]
        data = {
            "clusters": [{
                "description": "surfer in black wetsuit",
                "confidence": "low",
                "appearances": [
                    {"clip_index": 0, "person_id": "person_A"},
                    {"clip_index": 1, "person_id": "person_A"},
                ],
            }]
        }

        clusters = identity._build_clusters_from_data(data, clips)

        self.assertEqual(len(clusters), 2)
        self.assertTrue(all(len(c["appearances"]) == 1 for c in clusters))

    def test_conflicting_jersey_numbers_are_split(self):
        clips = [
            _clip("clip0.mp4", [_person("person_A", "player #7 red shirt")]),
            _clip("clip1.mp4", [_person("person_A", "player #23 red shirt")]),
        ]
        data = {
            "clusters": [{
                "description": "red shirt player",
                "confidence": "high",
                "appearances": [
                    {"clip_index": 0, "person_id": "person_A"},
                    {"clip_index": 1, "person_id": "person_A"},
                ],
            }]
        }

        clusters = identity._build_clusters_from_data(data, clips)

        self.assertEqual(len(clusters), 2)
        self.assertTrue(all(len(c["appearances"]) == 1 for c in clusters))

    def test_omitted_detected_person_is_preserved_as_singleton(self):
        clips = [
            _clip("clip0.mp4", [
                _person("person_A", "surfer with red board"),
                _person("person_B", "surfer with blue board"),
            ])
        ]
        partial = [{
            "description": "surfer with red board",
            "appearances": [{
                "path": "clip0.mp4",
                "events": [{"start": 1.0, "end": 8.0, "score": 8}],
                "_clip_index": 0,
                "_person_id": "person_A",
            }],
        }]

        clusters = identity._post_process_clusters(partial, clips)

        self.assertEqual(len(clusters), 2)
        descriptions = {c["description"] for c in clusters}
        self.assertIn("surfer with red board", descriptions)
        self.assertIn("surfer with blue board", descriptions)

    def test_cluster_clips_prefers_visual_before_clip_fallback(self):
        clips = [
            _clip("clip0.mp4", [_person("person_A", "surfer with red board")]),
            _clip("clip1.mp4", [_person("person_A", "surfer with red board")]),
        ]

        visual_result = [{
            "description": "surfer with red board",
            "appearances": [
                {
                    "path": "clip0.mp4",
                    "events": [{"start": 1.0, "end": 8.0, "score": 8}],
                    "_clip_index": 0,
                    "_person_id": "person_A",
                },
                {
                    "path": "clip1.mp4",
                    "events": [{"start": 1.0, "end": 8.0, "score": 8}],
                    "_clip_index": 1,
                    "_person_id": "person_A",
                },
            ],
        }]

        with patch.object(identity, "_try_visual_cluster", return_value=visual_result) as visual, \
             patch.object(identity, "_text_cluster", side_effect=AssertionError("text should not run")), \
             patch.object(identity, "_try_clip_cluster", side_effect=AssertionError("clip should not run")):
            clusters = identity.cluster_clips(clips)

        visual.assert_called_once()
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]["appearances"]), 2)


if __name__ == "__main__":
    unittest.main()
