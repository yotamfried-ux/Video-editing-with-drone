#!/usr/bin/env python3
"""Regression: every production render path is video-only and silent."""
from __future__ import annotations

import importlib.util
import math
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
POLICY_PATH = ROOT / "pipeline/silent_output_policy.py"


def load_policy():
    spec = importlib.util.spec_from_file_location("silent_output_policy_contract", POLICY_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("could not load silent output policy")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    silent = load_policy()

    compile_calls: list[tuple[tuple, dict]] = []
    bookend_calls: list[tuple[str, float, bool]] = []

    def original_compile(*args, **kwargs):
        compile_calls.append((args, kwargs))
        return "silent.mp4"

    def original_bookend(path: str, duration: float, has_audio: bool = False):
        bookend_calls.append((path, duration, has_audio))

    fake_editor = types.SimpleNamespace(
        _pick_music=lambda _sport="": "music/song.mp3",
        compile_reel=original_compile,
        _add_loop_bookend=original_bookend,
    )

    import pipeline.stages as stages

    original_editor = getattr(stages, "editor", None)
    stages.editor = fake_editor
    try:
        silent._patch_editor()
        if fake_editor._pick_music("football") is not None:
            raise SystemExit("music picker remained active")

        result = fake_editor.compile_reel(
            ["clip.mp4"],
            "logo.png",
            "out.mp4",
            sport="football",
            athlete_label="player #7",
            music_path="music/song.mp3",
        )
        if result != "silent.mp4":
            raise SystemExit("silent compile wrapper changed the renderer result")
        if compile_calls[-1][1].get("music_path") is not None:
            raise SystemExit("keyword music_path reached the renderer")

        fake_editor.compile_reel(
            ["clip.mp4"],
            "logo.png",
            "out.mp4",
            "surfing",
            "surfer A",
            "music/song.mp3",
        )
        if len(compile_calls[-1][0]) <= 5 or compile_calls[-1][0][5] is not None:
            raise SystemExit("positional music_path reached the renderer")

        fake_editor._add_loop_bookend("out.mp4", 30.0, has_audio=True)
        if bookend_calls[-1] != ("out.mp4", 30.0, False):
            raise SystemExit("loop bookend was allowed to preserve audio")
    finally:
        if original_editor is None:
            delattr(stages, "editor")
        else:
            stages.editor = original_editor

    with tempfile.TemporaryDirectory(prefix="sportreel-silent-output-") as directory:
        tmp = Path(directory)
        clean = tmp / "MULTI_target.mp4"
        music = tmp / "MULTI_target_music.mp4"
        clean.write_bytes(b"silent")
        music.write_bytes(b"audio")
        specs = {
            str(clean): {
                "has_audio": False,
                "duration": 30.0,
                "width": 1080,
                "height": 1920,
                "aspect": 1080 / 1920,
            },
            str(music): {
                "has_audio": True,
                "duration": 30.0,
                "width": 1080,
                "height": 1920,
                "aspect": 1080 / 1920,
            },
        }
        calls: dict[str, int] = {}

        def inspect(path: str) -> dict:
            calls[path] = calls.get(path, 0) + 1
            return specs[path]

        selected, events, failures = silent.canonicalize_silent_variants(
            [str(clean), str(music)],
            [(str(clean), [{"event_id": "wave-1"}]), (str(music), [{"event_id": "wave-1"}])],
            specs_getter=inspect,
        )
        if selected != [str(clean)] or failures:
            raise SystemExit(f"silent canonical output was not selected: {selected}, {failures}")
        if music.exists():
            raise SystemExit("legacy music variant remained on disk")
        if events != [(str(clean), [{"event_id": "wave-1"}])]:
            raise SystemExit("silent selection lost event evidence")
        if calls != {str(clean): 1, str(music): 1}:
            raise SystemExit(f"media variants were inspected more than once: {calls}")

    valid = {
        "has_audio": False,
        "duration": 30.0,
        "width": 1080,
        "height": 1920,
        "aspect": 1080 / 1920,
    }
    if silent.silent_social_ready_issues(valid):
        raise SystemExit("valid silent output was rejected")
    if "unexpected_audio" not in silent.silent_social_ready_issues(valid | {"has_audio": True}):
        raise SystemExit("audio-bearing output was not rejected")
    if "audio_state_unknown" not in silent.silent_social_ready_issues(valid | {"has_audio": None}):
        raise SystemExit("unknown audio state did not fail closed")
    if "invalid_duration" not in silent.silent_social_ready_issues(valid | {"duration": math.nan}):
        raise SystemExit("NaN duration was not rejected by the runtime policy")
    if "invalid_duration" not in silent.silent_social_ready_issues(valid | {"duration": math.inf}):
        raise SystemExit("infinite duration was not rejected by the runtime policy")
    if "aspect_not_9_16" not in silent.silent_social_ready_issues(valid | {"aspect": math.nan}):
        raise SystemExit("NaN aspect was not rejected by the runtime policy")

    source = POLICY_PATH.read_text(encoding="utf-8")
    required = [
        "math.isfinite",
        "specs_by_path",
        "editor._pick_music = no_music_picker",
        "editor.compile_reel = compile_silent",
        "editor._add_loop_bookend = silent_bookend",
        "policy.social_ready_issues = silent_social_ready_issues",
        "policy.canonicalize_publishable_variants = canonicalize_silent_variants",
    ]
    missing = [token for token in required if token not in source]
    if missing:
        raise SystemExit(f"silent runtime source missing contract tokens: {missing}")

    print("Silent output runtime contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
