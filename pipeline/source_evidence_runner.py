"""Optional source-window evidence runner for reel QA."""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pipeline.source_evidence import make_source_clips, source_evidence_prompt

BLOCKING_CONTEXT_TYPES = {"RIDE_BOUNDARY_UNCERTAIN", "MID_RIDE_CUT", "RIDE_SPLIT", "IDENTITY_UNCERTAIN"}
_QA_RESPONSE_ATTEMPTS = 2


def _context_defects(context: dict[str, Any]) -> list[dict[str, Any]]:
    defects = []
    for win in context.get("source_windows", []) or []:
        for item in win.get("duplicate_evidence", []) or []:
            dtype = str(item.get("defect_type") or item.get("type") or "").upper()
            if dtype in BLOCKING_CONTEXT_TYPES:
                defects.append({**item, "type": dtype, "severity": "critical", "blocking": True})
    return defects


def _parse_qa_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"): text = text[3:]
    if text.rstrip().endswith("```"): text = text.rstrip()[:-3]
    parsed = json.loads(text.strip())
    if not isinstance(parsed, dict): raise ValueError("QA response must be a JSON object")
    if not isinstance(parsed.get("defects", []), list): raise ValueError("QA defects must be an array")
    int(parsed.get("engagement_score", 0))
    return parsed

def _remember_final_qa(reel_path: str, result: dict[str, Any]) -> dict[str, Any]:
    """Preserve source-evidence verdict for the active render-to-QA invocation.

    Successful multimodal QA does not invoke the base analyzer's QA wrapper.
    Preserve the final result explicitly; outside publishable QA, be a no-op.
    """
    from pipeline.publishable_pending_scope import current_scope_token

    token = current_scope_token()
    if token:
        from pipeline.publishable_qa_evidence import record_qa_result

        record_qa_result(reel_path, result, invocation_token=token)
    return result


def with_source_evidence(analyzer: Any, original, reel_path: str, *args, context: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
    if not context:
        return _remember_final_qa(reel_path, original(reel_path, *args, **kwargs))
    clips = make_source_clips(context)
    if not clips:
        result = original(reel_path, *args, **kwargs)
        extra = _context_defects(context)
        if extra:
            result.update({"verdict": "FAIL", "defects": [*(result.get("defects", []) or []), *extra], "qa_review_required": True})
        return _remember_final_qa(reel_path, result)
    uploaded = []
    proxies: list[str] = []
    try:
        sport = str(kwargs.get("sport", ""))
        label = str(kwargs.get("athlete_label", ""))
        specs, tech_ok, issues = analyzer._check_technical_compliance(reel_path)
        qa_proxy = analyzer._make_qa_proxy(reel_path) if hasattr(analyzer, "_make_qa_proxy") else None
        if qa_proxy:
            proxies.append(qa_proxy)
        # Upload the draft and every source window concurrently: each upload mostly waits on
        # Gemini's file processing, so total wait is the slowest one, not the sum.
        paths = [qa_proxy or reel_path, *clips]
        with ThreadPoolExecutor(max_workers=min(4, len(paths))) as pool:
            futures = [pool.submit(analyzer._upload_video, path) for path in paths]
        errors = []
        for future in futures:
            try:
                uploaded.append(future.result())
            except Exception as upload_exc:  # keep successes so the finally block deletes them
                errors.append(upload_exc)
        if errors:
            raise errors[0]
        prompt = analyzer._QA_REEL_PROMPT
        if sport:
            prompt += "\nSport context: " + sport
        prompt += "\nAthlete: " + label + source_evidence_prompt(context)
        model = analyzer.genai.GenerativeModel(model_name=analyzer._QA_REEL_MODEL)
        parsed = None
        last_error = None
        for _attempt in range(_QA_RESPONSE_ATTEMPTS):
            try:
                resp = analyzer._with_retry(lambda: model.generate_content(uploaded + [prompt], request_options={"timeout": 120}))
                parsed = _parse_qa_json(resp.text)
                break
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                last_error = exc
        if parsed is None:
            result = original(reel_path, *args, **kwargs)
            defects = list(result.get("defects", []) or []) + _context_defects(context)
            defects.append({"type": "QA_REVIEW_REQUIRED", "severity": "critical", "note": f"source evidence QA response unavailable after {_QA_RESPONSE_ATTEMPTS} attempts: {last_error}"})
            result.update({"verdict": "FAIL", "defects": defects, "source_evidence_clip_count": len(clips), "source_evidence_visual_uploaded": True, "qa_review_required": True, "qa_failure_reason": "response_parse_failed"})
            return _remember_final_qa(reel_path, result)
        defects = [d for d in (parsed.get("defects") or []) if isinstance(d, dict)] + _context_defects(context)
        critical = [d for d in defects if str(d.get("severity", "")).lower() == "critical"]
        score = int(parsed.get("engagement_score", 0))
        threshold = int(os.getenv("QA_ENGAGEMENT_THRESHOLD", "60"))
        result = {"verdict": "PASS" if tech_ok and score >= threshold and not critical else "FAIL", "technical": {"pass": tech_ok, "issues": issues, **specs}, "content": parsed.get("content", {}), "defects": defects, "engagement_score": score, "overall": parsed.get("overall", ""), "source_evidence_clip_count": len(clips), "source_evidence_visual_uploaded": True, "qa_review_required": bool(critical)}
        analyzer._persist_qa_result(result, reel_path, sport)
        return _remember_final_qa(reel_path, result)
    except Exception as exc:
        result = original(reel_path, *args, **kwargs)
        defects = list(result.get("defects", []) or []) + _context_defects(context)
        defects.append({"type": "QA_REVIEW_REQUIRED", "severity": "critical", "note": f"source evidence upload/generation failed: {type(exc).__name__}: {exc}"})
        result.update({"verdict": "FAIL", "defects": defects, "source_evidence_clip_count": len(clips), "source_evidence_visual_uploaded": False, "qa_review_required": True})
        return _remember_final_qa(reel_path, result)
    finally:
        for item in uploaded:
            try:
                analyzer._delete_video(item)
            except Exception:
                pass
        for clip in [*clips, *proxies]:
            try:
                os.remove(clip)
            except OSError:
                pass
