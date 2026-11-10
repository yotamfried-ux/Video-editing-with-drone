"""Create source-window clips for QA evidence."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

MAX_WINDOWS = 4
PAD_BEFORE = 2.0
PAD_AFTER = 4.0
# Evidence clip path -> the source window it shows. The QA runner labels each uploaded video with this, so the
# model can tell the draft from the un-cropped source footage (pipeline.source_evidence_runner).
_CLIP_WINDOWS: dict[str, dict[str, Any]] = {}


def clip_window(path: str) -> dict[str, Any] | None:
    return _CLIP_WINDOWS.get(os.path.abspath(str(path)))


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def make_source_clips(context: dict[str, Any], tmp_dir: str | None = None) -> list[str]:
    tmp_dir = tmp_dir or os.getenv("TMP_DIR", "/tmp/dtor")
    os.makedirs(tmp_dir, exist_ok=True)
    clips: list[str] = []
    for idx, win in enumerate(context.get("source_windows", [])[:MAX_WINDOWS]):
        src = str(win.get("source") or "")
        if not src or not os.path.exists(src):
            continue
        start = max(0.0, _num(win.get("source_start")) - PAD_BEFORE)
        end = max(start + 0.5, _num(win.get("source_end")) + PAD_AFTER)
        out = os.path.join(tmp_dir, f"qa_src_{Path(src).stem}_{idx:02d}.mp4")
        # The perception single decode left a near-transparent 1280 px copy of exactly this source file:
        # cutting from it avoids decoding the 4K window again while the next reel renders. Same filter and
        # encoder settings as below, so the evidence clip is the same size and quality.
        try:
            from pipeline.perception.single_decode import evidence_copy_for

            cut_from = evidence_copy_for(src) or src
        except Exception:
            cut_from = src
        def _small_reencode(input_path: str) -> None:
            # Small re-encode (<=1280px wide, silent) so the upload is a few MB, not the 4K window.
            subprocess.run(["ffmpeg", "-y", "-ss", str(start), "-i", input_path, "-t", str(end - start),
                            "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "26", "-pix_fmt", "yuv420p", "-an", out],
                           capture_output=True, timeout=180, check=True)

        try:
            try:
                try:
                    _small_reencode(cut_from)
                except Exception:
                    if cut_from == src:
                        raise
                    _small_reencode(src)  # evidence copy unusable: the original 4K path
            except Exception:
                subprocess.run(["ffmpeg", "-y", "-ss", str(start), "-i", src, "-t", str(end - start), "-c", "copy", out], capture_output=True, timeout=120, check=True)
            if os.path.exists(out):
                clips.append(out)
                try:
                    from integrations.ffmpeg import get_duration

                    recording_end = float(get_duration(src))
                    if not 0 < recording_end < float("inf"):
                        recording_end = None
                except Exception:
                    recording_end = None
                _CLIP_WINDOWS[os.path.abspath(out)] = {
                    "recording_end": round(recording_end, 2) if recording_end else None,
                    "window_index": idx,
                    "source": Path(src).name,
                    "source_start": _num(win.get("source_start")),
                    "source_end": _num(win.get("source_end")),
                    "clip_start": round(start, 2),
                    "clip_end": round(end, 2),
                    "rendered_timeline_start": win.get("rendered_timeline_start"),
                    "rendered_timeline_end": win.get("rendered_timeline_end"),
                }
        except Exception:
            try:
                os.remove(out)
            except OSError:
                pass
    return clips


def source_evidence_prompt(context: dict[str, Any]) -> str:
    data = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    return "\nSOURCE_EVIDENCE_JSON:\n" + data + "\nAdditional videos after the draft are original source windows with padding. Compare the final draft against them for identity continuity, timing, and repeated source windows."
