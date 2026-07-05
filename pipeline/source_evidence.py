"""Create source-window clips for QA evidence."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import config

MAX_WINDOWS = 4
PAD_BEFORE = 2.0
PAD_AFTER = 4.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def make_source_clips(context: dict[str, Any], tmp_dir: str | None = None) -> list[str]:
    tmp_dir = tmp_dir or config.TMP_DIR
    os.makedirs(tmp_dir, exist_ok=True)
    clips: list[str] = []
    for idx, win in enumerate(context.get("source_windows", [])[:MAX_WINDOWS]):
        src = str(win.get("source") or "")
        if not src or not os.path.exists(src):
            continue
        start = max(0.0, _num(win.get("source_start")) - PAD_BEFORE)
        end = max(start + 0.5, _num(win.get("source_end")) + PAD_AFTER)
        out = os.path.join(tmp_dir, f"qa_src_{Path(src).stem}_{idx:02d}.mp4")
        try:
            subprocess.run(["ffmpeg", "-y", "-ss", str(start), "-i", src, "-t", str(end - start), "-c", "copy", out], capture_output=True, timeout=120, check=True)
            if os.path.exists(out):
                clips.append(out)
        except Exception:
            try:
                os.remove(out)
            except OSError:
                pass
    return clips


def source_evidence_prompt(context: dict[str, Any]) -> str:
    data = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    return "\nSOURCE_EVIDENCE_JSON:\n" + data + "\nAdditional videos after the draft are original source windows with padding. Compare the final draft against them for identity continuity, timing, and repeated source windows."
