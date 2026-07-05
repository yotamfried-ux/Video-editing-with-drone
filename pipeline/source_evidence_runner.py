"""Optional source-window evidence runner for reel QA."""
from __future__ import annotations

import json
import os
from typing import Any

from pipeline.source_evidence import make_source_clips, source_evidence_prompt

BLOCKING_CONTEXT_TYPES = {"RIDE_BOUNDARY_UNCERTAIN", "MID_RIDE_CUT", "RIDE_SPLIT", "IDENTITY_UNCERTAIN"}


def _context_defects(context: dict[str, Any]) -> list[dict[str, Any]]:
    defects = []
    for win in context.get("source_windows", []) or []:
        for item in win.get("duplicate_evidence", []) or []:
            dtype = str(item.get("defect_type") or item.get("type") or "").upper()
            if dtype in BLOCKING_CONTEXT_TYPES:
                defects.append({**item, "type": dtype, "severity": "critical", "blocking": True})
    return defects


def with_source_evidence(analyzer: Any, original, reel_path: str, *args, context: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
    if not context:
        return original(reel_path, *args, **kwargs)
    clips = make_source_clips(context)
    if not clips:
        result = original(reel_path, *args, **kwargs)
        extra = _context_defects(context)
        if extra:
            result.update({"verdict": "FAIL", "defects": [*(result.get("defects", []) or []), *extra], "qa_review_required": True})
        return result
    uploaded = []
    try:
        sport = str(kwargs.get("sport", ""))
        label = str(kwargs.get("athlete_label", ""))
        specs, tech_ok, issues = analyzer._check_technical_compliance(reel_path)
        uploaded.append(analyzer._upload_video(reel_path))
        for clip in clips:
            uploaded.append(analyzer._upload_video(clip))
        prompt = analyzer._QA_REEL_PROMPT
        if sport:
            prompt += "\nSport context: " + sport
        prompt += "\nAthlete: " + label + source_evidence_prompt(context)
        model = analyzer.genai.GenerativeModel(model_name=analyzer._QA_REEL_MODEL)
        resp = analyzer._with_retry(lambda: model.generate_content(uploaded + [prompt], request_options={"timeout": 120}))
        parsed = json.loads(resp.text.strip().strip("`").strip())
        defects = [d for d in (parsed.get("defects") or []) if isinstance(d, dict)] + _context_defects(context)
        critical = [d for d in defects if str(d.get("severity", "")).lower() == "critical"]
        score = int(parsed.get("engagement_score", 0))
        threshold = int(os.getenv("QA_ENGAGEMENT_THRESHOLD", "60"))
        result = {"verdict": "PASS" if tech_ok and score >= threshold and not critical else "FAIL", "technical": {"pass": tech_ok, "issues": issues, **specs}, "content": parsed.get("content", {}), "defects": defects, "engagement_score": score, "overall": parsed.get("overall", ""), "source_evidence_clip_count": len(clips), "source_evidence_visual_uploaded": True, "qa_review_required": bool(critical)}
        analyzer._persist_qa_result(result, reel_path, sport)
        return result
    except Exception:
        result = original(reel_path, *args, **kwargs)
        defects = list(result.get("defects", []) or []) + _context_defects(context)
        defects.append({"type": "QA_REVIEW_REQUIRED", "severity": "critical", "note": "source evidence upload failed"})
        result.update({"verdict": "FAIL", "defects": defects, "source_evidence_clip_count": len(clips), "source_evidence_visual_uploaded": False, "qa_review_required": True})
        return result
    finally:
        for item in uploaded:
            try:
                analyzer._delete_video(item)
            except Exception:
                pass
        for clip in clips:
            try:
                os.remove(clip)
            except OSError:
                pass
