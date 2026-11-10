"""Optional source-window evidence runner for reel QA."""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pipeline.source_evidence import clip_window, make_source_clips, source_evidence_prompt

BLOCKING_CONTEXT_TYPES = {"RIDE_BOUNDARY_UNCERTAIN", "MID_RIDE_CUT", "RIDE_SPLIT", "IDENTITY_UNCERTAIN"}
_QA_RESPONSE_ATTEMPTS = 2
# A defect timestamped this far past the draft's end cannot describe the draft.
_OUT_OF_DRAFT_TOLERANCE_SEC = 1.0


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return "?"


_DJI_CLOCK = re.compile(r"DJI_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})_\d{4}")


def _camera_clock(source_name: str, start: Any, end: Any) -> str:
    """Wall-clock span of a DJI window from the file name's recording start (camera clock).

    All drone files in run 42814819534 are one camera's numbered sequence, so two windows from different files
    can never be one moment; the model called two similar waves 12 minutes apart "the same ride from two
    perspectives". The capture time lets it tell them apart.
    """
    match = _DJI_CLOCK.search(str(source_name or ""))
    if not match:
        return ""
    try:
        year, month, day, hour, minute, second = (int(g) for g in match.groups())
        base = hour * 3600 + minute * 60 + second

        def clock(offset: Any) -> str:
            total = base + float(offset)
            return f"{int(total // 3600) % 24:02d}:{int(total // 60) % 60:02d}:{total % 60:04.1f}"

        return f" Recorded {year:04d}-{month:02d}-{day:02d} {clock(start)}-{clock(end)} (camera clock)."
    except (TypeError, ValueError):
        return ""


def _labeled_parts(uploaded: list[Any], clips: list[str], draft_duration: Any) -> list[Any]:
    """Interleave a text label before every uploaded video.

    Run 42814819534 sent [draft, source, source, ..., prompt] with one closing sentence saying "additional
    videos after the draft are source windows". The model read them as ONE continuous video: findings at @7s
    on a 5.0 s reel, "duplicated, only reframed" (the reel against its own source window), "a wider shot
    featuring three different surfers" (the un-cropped source) and "a clip not in the manifest".
    """
    total = len(uploaded)
    parts: list[Any] = [
        f"VIDEO 1 of {total} - THE FINAL DRAFT REEL ({_fmt(draft_duration)} long). This is the ONLY video you score. "
        "Every defect and every at_seconds refers to this video's own timeline (0 to its length).",
        uploaded[0],
    ]
    for number, (handle, clip) in enumerate(zip(uploaded[1:], clips), start=2):
        meta = clip_window(clip) or {}
        where = ""
        if meta:
            where = (f" Original footage of {meta.get('source', 'the source')} from {_fmt(meta.get('clip_start'))} to "
                     f"{_fmt(meta.get('clip_end'))}: the draft used {_fmt(meta.get('source_start'))}-"
                     f"{_fmt(meta.get('source_end'))} of it (padding before and after shows what the cut left out)")
            if meta.get("rendered_timeline_start") is not None:
                where += (f", at draft time {_fmt(meta.get('rendered_timeline_start'))}-"
                          f"{_fmt(meta.get('rendered_timeline_end'))}")
            where += "." + _camera_clock(meta.get("source", ""), meta.get("source_start"), meta.get("source_end"))
            recording_end = meta.get("recording_end")
            if recording_end:
                where += f" The recording itself ends at {_fmt(recording_end)}."
                try:
                    if float(meta.get("source_end")) >= float(recording_end) - 0.15:
                        where += (" The draft already uses this window up to the last recorded frame: nothing exists "
                                  "after it, so a ride that is still going there was cut by the camera, not by the "
                                  "edit. Report that at most as a minor PREMATURE_CUT.")
                except (TypeError, ValueError):
                    pass
        parts += [
            f"VIDEO {number} of {total} - SOURCE EVIDENCE, NOT PART OF THE REEL.{where} It is un-cropped, so it "
            "shows a wider view and other people. Use it only to judge the draft: whether a cut ends a ride early, "
            "whether the draft shows the same athlete, whether two draft clips repeat one moment. Never report "
            "this video's own content as a defect of the reel, and never compare the reel against it as a "
            "duplicate: the draft is expected to contain this footage, reframed.",
            handle,
        ]
    return parts


def _split_out_of_draft(defects: list[dict[str, Any]], draft_duration: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Defects whose at_seconds lies past the draft's end describe a source-evidence video, not the draft."""
    try:
        limit = float(draft_duration) + _OUT_OF_DRAFT_TOLERANCE_SEC
    except (TypeError, ValueError):
        return defects, []
    kept: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    for defect in defects:
        try:
            at = float(defect.get("at_seconds"))
        except (TypeError, ValueError):
            kept.append(defect)
            continue
        if at > limit:
            out.append({**defect, "discarded_reason": "at_seconds_outside_draft", "draft_duration": float(draft_duration)})
        else:
            kept.append(defect)
    return kept, out


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
        parts = _labeled_parts(uploaded, clips, specs.get("duration") if isinstance(specs, dict) else None)
        prompt = analyzer._QA_REEL_PROMPT + getattr(analyzer, "_QA_LAYOUT_NOTE", "")
        if sport:
            prompt += "\nSport context: " + sport
        prompt += "\nAthlete: " + label + source_evidence_prompt(context)
        model = analyzer.genai.GenerativeModel(model_name=analyzer._QA_REEL_MODEL)
        parsed = None
        last_error = None
        for _attempt in range(_QA_RESPONSE_ATTEMPTS):
            try:
                resp = analyzer._with_retry(lambda: model.generate_content(parts + [prompt], request_options={"timeout": 120}))
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
        model_defects, out_of_draft = _split_out_of_draft(
            [d for d in (parsed.get("defects") or []) if isinstance(d, dict)],
            specs.get("duration") if isinstance(specs, dict) else None)
        defects = model_defects + _context_defects(context)
        for item in out_of_draft:
            print(f"     ⚪ QA finding outside the {float(item['draft_duration']):.1f}s draft ignored: "
                  f"{item.get('type')} @{item.get('at_seconds')}s — {str(item.get('note', ''))[:120]}")
        critical = [d for d in defects if str(d.get("severity", "")).lower() == "critical"]
        score = int(parsed.get("engagement_score", 0))
        threshold = int(os.getenv("QA_ENGAGEMENT_THRESHOLD", "60"))
        result = {"verdict": "PASS" if tech_ok and score >= threshold and not critical else "FAIL", "technical": {"pass": tech_ok, "issues": issues, **specs}, "content": parsed.get("content", {}), "defects": defects, "engagement_score": score, "overall": parsed.get("overall", ""), "source_evidence_clip_count": len(clips), "source_evidence_visual_uploaded": True, "qa_review_required": bool(critical), "out_of_draft_defects": out_of_draft}
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
