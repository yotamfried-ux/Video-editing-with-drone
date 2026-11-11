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
# A cut finding on a clip whose window already reaches the last recorded frame. The edit cannot add footage the
# camera never recorded, so this is reported for information and never blocks approval or starts a re-edit.
# Run 42891165218: every one of 12 reels was "QA failed - re-edit required / approval blocked" for PREMATURE_CUT,
# and QA's own notes said "due to the camera recording ending, not an editing choice" on 19 of 22 findings.
RECORDING_LIMITED_TYPE = "RECORDING_ENDS_MID_ACTION"
_CUT_DEFECT_TYPES = {"PREMATURE_CUT", "CUT_TOO_EARLY"}
_RECORDING_END_EPS_SEC = 0.15
# QA timestamps a cut at roughly the second it happens; whole seconds on a clip boundary need this slack.
_CLIP_BOUNDARY_TOLERANCE_SEC = 1.0


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
                                  f"edit. Report that as {RECORDING_LIMITED_TYPE}, never as PREMATURE_CUT.")
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


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _recording_end_of(source: str, known: dict[str, float]) -> float | None:
    """Length of a source recording: from the evidence clips already measured, else probed once."""
    name = os.path.basename(str(source or ""))
    if name in known:
        return known[name]
    if not source or not os.path.exists(str(source)):
        return None
    try:
        from integrations.ffmpeg import get_duration

        duration = _to_float(get_duration(str(source)))
    except Exception:
        duration = None
    if duration is not None and duration > 0:
        known[name] = duration
        return duration
    return None


def draft_clip_facts(context: dict[str, Any], clips: list[str] | None = None) -> list[dict[str, Any]]:
    """What is known, without a model, about every clip of the draft: its place on the draft timeline, its
    source window, where its recording ends and whether the window already reaches that end.

    Covers every source window of the draft, not only the first `MAX_WINDOWS` that get an evidence video.
    """
    known: dict[str, float] = {}
    for clip in clips or []:
        meta = clip_window(clip) or {}
        end = _to_float(meta.get("recording_end"))
        if meta.get("source") and end:
            known[str(meta["source"])] = end
    facts: list[dict[str, Any]] = []
    for index, win in enumerate(context.get("source_windows", []) or []):
        if not isinstance(win, dict):
            continue
        source_end = _to_float(win.get("source_end"))
        recording_end = _recording_end_of(str(win.get("source") or ""), known)
        facts.append({
            "clip_index": index + 1,
            "source": os.path.basename(str(win.get("source") or "")),
            "draft_start": _to_float(win.get("rendered_timeline_start")),
            "draft_end": _to_float(win.get("rendered_timeline_end")),
            "source_start": _to_float(win.get("source_start")),
            "source_end": source_end,
            "recording_end": recording_end,
            "reaches_recording_end": bool(source_end is not None and recording_end is not None
                                          and source_end >= recording_end - _RECORDING_END_EPS_SEC),
        })
    return facts


def _clip_of_cut(at_seconds: Any, facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The draft clip a cut finding at `at_seconds` refers to, or None when that cannot be told."""
    if not facts:
        return None
    if len(facts) == 1:
        return facts[0]
    if all(fact["reaches_recording_end"] for fact in facts):
        return facts[0]  # whichever clip it is, the answer is the same
    at = _to_float(at_seconds)
    timed = [f for f in facts if f["draft_start"] is not None and f["draft_end"] is not None]
    if at is None or len(timed) != len(facts):
        return None
    inside = [f for f in timed if f["draft_start"] - _CLIP_BOUNDARY_TOLERANCE_SEC < at <= f["draft_end"] + _CLIP_BOUNDARY_TOLERANCE_SEC]
    if not inside:
        return None
    # A cut is reported where the clip ends, so the clip whose end is nearest is the one meant.
    return min(inside, key=lambda f: abs(f["draft_end"] - at))


def reclassify_recording_limited(defects: list[dict[str, Any]], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn cut findings on clips that already run to the last recorded frame into a non-blocking note.

    Decided from the windows, not from the model's wording: the model may or may not say "the camera stopped".
    A cut finding on a clip that ends before its recording does is left exactly as it was.
    """
    out: list[dict[str, Any]] = []
    for defect in defects:
        dtype = str(defect.get("type", "")).upper()
        if dtype not in _CUT_DEFECT_TYPES and dtype != RECORDING_LIMITED_TYPE:
            out.append(defect)
            continue
        clip = _clip_of_cut(defect.get("at_seconds"), facts)
        limited = clip is not None and clip["reaches_recording_end"]
        if dtype == RECORDING_LIMITED_TYPE and not limited:
            # The reviewer blamed the camera, but footage exists after this cut (or the clip is unknown): that is
            # an ordinary cut finding and must keep blocking.
            out.append({**defect, "type": "PREMATURE_CUT", "reported_type": RECORDING_LIMITED_TYPE})
            continue
        if not limited:
            out.append(defect)
            continue
        out.append({**defect, "type": RECORDING_LIMITED_TYPE, "severity": "info", "original_type": dtype,
                    "original_severity": str(defect.get("severity", "")).lower(), "actionable": False,
                    "clip_index": clip["clip_index"], "source": clip["source"],
                    "recording_end": clip["recording_end"]})
    return out


def _clip_facts_prompt(facts: list[dict[str, Any]]) -> str:
    """Tell the reviewer, per draft clip, what the edit could and could not have done, and ask for a verdict on
    each clip's opening and ending. The verdicts are stored for measurement; they do not gate anything."""
    if not facts:
        return ""
    lines = ["", "DRAFT CLIPS (facts measured from the files, not opinions):"]
    for fact in facts:
        span = ""
        if fact["draft_start"] is not None and fact["draft_end"] is not None:
            span = f" draft {_fmt(fact['draft_start'])}-{_fmt(fact['draft_end'])};"
        line = (f"- clip {fact['clip_index']}:{span} source {fact['source']} "
                f"{_fmt(fact['source_start'])}-{_fmt(fact['source_end'])}")
        if fact["recording_end"] is not None:
            line += f"; the recording ends at {_fmt(fact['recording_end'])}"
            if fact["reaches_recording_end"]:
                line += " = this clip ALREADY RUNS TO THE LAST RECORDED FRAME"
            else:
                line += f" ({_fmt(fact['recording_end'] - fact['source_end'])} of footage exists after the cut)"
        lines.append(line)
    lines += [
        "A clip that already runs to the last recorded frame cannot be extended. If its action is still going at",
        f"the end, report {RECORDING_LIMITED_TYPE} (severity \"minor\") for it and NOT PREMATURE_CUT. Use",
        "PREMATURE_CUT only when footage exists after the cut and the action continues in it.",
        "Add to your JSON a \"clips\" array with one entry per draft clip, in order:",
        "  {\"clip_index\": <number>, \"opens_on_action\": true|false, \"seconds_to_first_action\": <number>,",
        "   \"ending\": \"complete\"|\"cut_by_edit\"|\"cut_by_camera\", \"dead_seconds\": <number>}",
        "opens_on_action: the athlete is already performing within the clip's first second. ending: \"complete\"",
        "when the action resolves in the clip (ride finishes, fall, kick-out). dead_seconds: total time in the",
        "clip with no meaningful action by the athlete.",
    ]
    return "\n".join(lines)


def _clip_reviews(parsed: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The reviewer's per-clip verdicts, corrected where they contradict the measured windows."""
    by_index = {fact["clip_index"]: fact for fact in facts}
    reviews: list[dict[str, Any]] = []
    for item in parsed.get("clips") or []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("clip_index"))
        except (TypeError, ValueError):
            continue
        fact = by_index.get(index)
        if fact is None:
            continue
        ending = str(item.get("ending") or "").lower()
        review = {"clip_index": index, "source": fact["source"], "opens_on_action": item.get("opens_on_action"),
                  "seconds_to_first_action": _to_float(item.get("seconds_to_first_action")),
                  "ending": ending, "dead_seconds": _to_float(item.get("dead_seconds")),
                  "reaches_recording_end": fact["reaches_recording_end"]}
        if ending == "cut_by_edit" and fact["reaches_recording_end"]:
            review.update({"ending": "cut_by_camera", "ending_corrected_from": "cut_by_edit"})
        reviews.append(review)
    return reviews


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
        facts = draft_clip_facts(context, clips)
        prompt += "\nAthlete: " + label + source_evidence_prompt(context) + _clip_facts_prompt(facts)
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
        defects = reclassify_recording_limited(model_defects, facts) + _context_defects(context)
        for item in defects:
            if item.get("type") == RECORDING_LIMITED_TYPE:
                print(f"     ⚪ {item.get('original_type')} @{item.get('at_seconds')}s is the end of the recording "
                      f"({item.get('source')}), not an edit: kept as a note, not blocking")
        for item in out_of_draft:
            print(f"     ⚪ QA finding outside the {float(item['draft_duration']):.1f}s draft ignored: "
                  f"{item.get('type')} @{item.get('at_seconds')}s — {str(item.get('note', ''))[:120]}")
        critical = [d for d in defects if str(d.get("severity", "")).lower() == "critical"]
        from pipeline.qa_gate_policy import qa_gate_score, qa_pass_threshold

        score = int(parsed.get("engagement_score", 0))
        gate = qa_gate_score(parsed)
        result = {"verdict": "PASS" if tech_ok and gate >= qa_pass_threshold() and not critical else "FAIL", "technical": {"pass": tech_ok, "issues": issues, **specs}, "content": parsed.get("content", {}), "defects": defects, "engagement_score": score, "deliverable_score": parsed.get("deliverable_score"), "gate_score": gate, "overall": parsed.get("overall", ""), "source_evidence_clip_count": len(clips), "source_evidence_visual_uploaded": True, "qa_review_required": bool(critical), "out_of_draft_defects": out_of_draft, "clip_reviews": _clip_reviews(parsed, facts), "draft_clip_facts": facts}
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
