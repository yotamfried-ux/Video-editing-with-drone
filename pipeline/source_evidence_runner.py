"""Optional source-window evidence runner for reel QA."""
from __future__ import annotations

import json
import os
from typing import Any

import config
from pipeline.source_evidence import make_source_clips, source_evidence_prompt


def with_source_evidence(analyzer: Any, original, reel_path: str, *args, context: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
    if not context:
        return original(reel_path, *args, **kwargs)
    clips = make_source_clips(context)
    if not clips:
        return original(reel_path, *args, **kwargs)
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
        defects = [d for d in (parsed.get("defects") or []) if isinstance(d, dict)]
        critical = [d for d in defects if str(d.get("severity", "")).lower() == "critical"]
        score = int(parsed.get("engagement_score", 0))
        ok = tech_ok and score >= config.QA_ENGAGEMENT_THRESHOLD and not critical
        result = {"verdict": "PASS" if ok else "FAIL", "technical": {"pass": tech_ok, "issues": issues, **specs}, "content": parsed.get("content", {}), "defects": defects, "engagement_score": score, "overall": parsed.get("overall", ""), "source_evidence_clip_count": len(clips), "source_evidence_visual_uploaded": True}
        analyzer._persist_qa_result(result, reel_path, sport)
        return result
    except Exception:
        result = original(reel_path, *args, **kwargs)
        defects = list(result.get("defects", []) or [])
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
