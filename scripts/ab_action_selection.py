#!/usr/bin/env python3
"""A/B check that a cost-saving analysis variant does not change WHICH actions get selected.

For a sample of real sources (read-only from R2 `processed/`) it runs the real Gemini session analysis
several times: a `control` (defaults), a second `control_repeat` (measures the model's own run-to-run
noise), and each candidate variant. Selected actions are compared by time overlap (IoU) against the
control. A variant passes only when its agreement with the control is within the noise floor of
control-vs-control, so ordinary LLM randomness is not mistaken for a regression (or hidden by one).

Nothing is written to storage or Supabase. The analysis cache is disabled so every run is a real call.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IOU_MATCH = 0.5
TOP_SCORE = 8
NOISE_TOLERANCE = 0.05

VARIANTS: dict[str, dict[str, str]] = {
    "control": {},
    "control_repeat": {},
    "lowres": {"ANALYSIS_MEDIA_RESOLUTION": "LOW"},
    "fps05": {"ANALYSIS_VIDEO_FPS": "0.5"},
    "trim": {"ANALYSIS_TRIM_TO_ACTIVITY": "1"},
    "combined": {"ANALYSIS_MEDIA_RESOLUTION": "LOW", "ANALYSIS_VIDEO_FPS": "0.5", "ANALYSIS_TRIM_TO_ACTIVITY": "1"},
}
_VARIANT_ENV_KEYS = {"ANALYSIS_MEDIA_RESOLUTION", "ANALYSIS_VIDEO_FPS", "ANALYSIS_TRIM_TO_ACTIVITY"}


# ── pure comparison logic (unit-tested) ─────────────────────────────────────

def flatten_events(session: dict[str, Any]) -> list[dict[str, float]]:
    """Every selected action of every athlete as {start, end, score}."""
    out: list[dict[str, float]] = []
    for person in session.get("persons", []) or []:
        for event in person.get("events", []) or []:
            try:
                out.append({"start": float(event["start"]), "end": float(event["end"]),
                            "score": float(event.get("score", 0))})
            except (KeyError, TypeError, ValueError):
                continue
    return out


def iou(a: dict[str, float], b: dict[str, float], shift_b: float = 0.0) -> float:
    start = max(a["start"], b["start"] + shift_b)
    end = min(a["end"], b["end"] + shift_b)
    inter = max(0.0, end - start)
    union = (a["end"] - a["start"]) + (b["end"] - b["start"]) - inter
    return inter / union if union > 0 else 0.0


def matched(reference: dict[str, float], candidates: list[dict[str, float]], shift: float = 0.0) -> bool:
    return any(iou(reference, c, shift) >= IOU_MATCH for c in candidates)


def agreement(reference: list[dict[str, float]], other: list[dict[str, float]], shift: float = 0.0) -> dict[str, Any]:
    """How much of the reference selection the other run reproduces (and what it adds)."""
    top = [e for e in reference if e["score"] >= TOP_SCORE]
    return {
        "reference_events": len(reference),
        "other_events": len(other),
        "recall": (sum(matched(e, other, shift) for e in reference) / len(reference)) if reference else None,
        "top_events": len(top),
        "top_recall": (sum(matched(e, other, shift) for e in top) / len(top)) if top else None,
        "extra": sum(1 for e in other if not matched(e, reference, -shift)),
    }


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def pooled(rows: list[dict[str, Any]], key: str, weight_key: str) -> float | None:
    """Event-weighted mean so a source with 12 actions counts more than one with 1."""
    pairs = [(r[key], r[weight_key]) for r in rows if r.get(key) is not None and r.get(weight_key)]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def judge(per_source: dict[str, dict[str, dict[str, Any]]], variant: str) -> dict[str, Any]:
    """Verdict for one variant versus the control, calibrated by control_repeat noise."""
    def metric(name: str) -> dict[str, Any]:
        rows = [src[name] for src in per_source.values() if name in src]
        return {"recall": pooled(rows, "recall", "reference_events"),
                "top_recall": pooled(rows, "top_recall", "top_events"),
                "extra": sum(r["extra"] for r in rows), "sources": len(rows)}
    noise, result = metric("control_repeat"), metric(variant)
    checks: dict[str, bool | None] = {}
    for key in ("recall", "top_recall"):
        checks[key] = (None if result[key] is None or noise[key] is None
                       else result[key] >= noise[key] - NOISE_TOLERANCE)
    persons_ok = [src[variant].get("same_person_count") for src in per_source.values() if variant in src]
    checks["person_count"] = (all(persons_ok) if persons_ok else None)
    checks["no_errors"] = not any(src[variant].get("errored") for src in per_source.values() if variant in src)
    verdict = "PASS" if all(v is True for v in checks.values()) else (
        "INCONCLUSIVE" if any(v is None for v in checks.values()) and not any(v is False for v in checks.values()) else "FAIL")
    return {"variant": variant, "verdict": verdict, "checks": checks, "result": result, "noise_floor": noise}


def detect_timeline_shift(reference: list[dict[str, float]], other: list[dict[str, float]], offset: float) -> bool:
    """True when the variant's events line up with the control only after adding the trim offset
    (i.e. Gemini reported times relative to the trimmed clip instead of the source timeline)."""
    if not reference or not other or offset <= 0:
        return False
    plain = sum(matched(e, other) for e in reference)
    shifted = sum(matched(e, other, offset) for e in reference)
    return shifted > plain


# ── runtime ─────────────────────────────────────────────────────────────────

def pick_sources(objects: list[dict[str, Any]], sample: int, min_bytes: int) -> list[dict[str, Any]]:
    """Deterministic, evenly spread sample of the long sources (stable between runs)."""
    longs = sorted((o for o in objects if int(o.get("Size") or o.get("size") or 0) > min_bytes),
                   key=lambda o: str(o.get("Key") or o.get("key")))
    if sample <= 0 or sample >= len(longs):
        return longs
    step = len(longs) / sample
    return [longs[int(i * step)] for i in range(sample)]


def _run_variant(name: str, env: dict[str, str], video: str) -> dict[str, Any]:
    from integrations import llm_cost
    import pipeline.stages.analyzer as analyzer
    for key in _VARIANT_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.update(env)
    before = len(llm_cost.snapshot())
    started = time.monotonic()
    error = None
    session: dict[str, Any] = {}
    try:
        session = analyzer.analyze_session(video)
    except Exception as exc:  # one failed call must not abort the whole A/B
        error = f"{type(exc).__name__}: {exc}"
    calls = llm_cost.snapshot()[before:]
    return {"variant": name, "seconds": round(time.monotonic() - started, 1), "error": error,
            "session": session, "calls": len(calls),
            "cost_usd": round(sum(c["cost_usd"] or 0.0 for c in calls), 5),
            "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
            "thinking_tokens": sum(c["thinking_tokens"] for c in calls)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=8)
    parser.add_argument("--variants", default="lowres,fps05,trim,combined")
    parser.add_argument("--out", default="/tmp/ab-action-selection")
    parser.add_argument("--min-mb", type=int, default=100)
    parser.add_argument("--local-dir", default="", help="analyse *.mp4 files from this directory instead of R2")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    os.environ["TMP_DIR"] = str(out / "tmp")
    os.environ["LLM_CACHE"] = "0"                      # every run must be a real model call
    os.environ["SPORTREEL_PERCEPTION_SIDECAR_DIR"] = str(out / "sidecars")
    os.environ.setdefault("SPORTREEL_PERCEPTION_COMMAND",
                          f"{sys.executable} scripts/generate_perception_sidecar.py {{video_path}} {{sidecar_path}} --backend ultralytics")
    os.environ.setdefault("SPORTREEL_ULTRALYTICS_MODEL", "yolo11s.pt")
    os.environ.setdefault("SPORTREEL_ULTRALYTICS_VID_STRIDE", "5")
    os.environ.setdefault("SPORTREEL_ULTRALYTICS_FPS", "30")
    Path(os.environ["TMP_DIR"]).mkdir(parents=True, exist_ok=True)

    import pipeline.stages.analyzer as analyzer
    analyzer._extract_thumbnail = lambda *a, **k: None          # thumbnails are irrelevant to selection
    import pipeline.stages.feedback as feedback
    feedback.get_all_label_injections = lambda: ""               # identical prompt in every variant
    feedback.get_operator_notes = lambda: ""
    feedback.get_negative_feedback_hint = lambda: ""

    names = ["control", "control_repeat", *[v for v in args.variants.split(",") if v]]
    unknown = [n for n in names if n not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variants: {unknown}")

    if args.local_dir:
        videos = [str(p) for p in sorted(Path(args.local_dir).glob("*.mp4"))][: args.sample or None]
    else:
        from integrations import r2_storage
        keys = pick_sources(r2_storage.list_objects(r2_storage.PROCESSED_PREFIX), args.sample, args.min_mb * 1_000_000)
        videos = []
        for item in keys:
            key = str(item.get("Key") or item.get("key"))
            local = str(out / "sources" / Path(key).name)
            Path(local).parent.mkdir(parents=True, exist_ok=True)
            print(f"⬇️  {key}", flush=True)
            r2_storage.download_object(key, local)
            videos.append(local)
    print(f"A/B sample: {len(videos)} source(s), variants: {names}", flush=True)

    from pipeline.perception.runtime import ensure_sidecar_for_video
    per_source: dict[str, dict[str, dict[str, Any]]] = {}
    runs: list[dict[str, Any]] = []
    shift_flags: dict[str, int] = {}
    for video in videos:
        label = Path(video).name
        try:
            ensure_sidecar_for_video(video)
        except Exception as exc:
            print(f"⚠️  no sidecar for {label}: {exc} (trim variants fall back to the whole video)", flush=True)
        results = {n: _run_variant(n, VARIANTS[n], video) for n in names}
        runs.extend({k: v for k, v in r.items() if k != "session"} | {"source": label} for r in results.values())
        reference = flatten_events(results["control"]["session"])
        person_count = len(results["control"]["session"].get("persons", []) or [])
        per_source[label] = {}
        for name in names[1:]:
            other = flatten_events(results[name]["session"])
            entry = agreement(reference, other)
            entry["same_person_count"] = len(results[name]["session"].get("persons", []) or []) == person_count
            entry["errored"] = bool(results[name]["error"])
            per_source[label][name] = entry
            if name in {"trim", "combined"}:
                from pipeline.activity_window import window_for_video
                from pipeline.stages.analyzer import _video_duration
                window = window_for_video(video, _video_duration(video))
                if window and detect_timeline_shift(reference, other, window[0]):
                    shift_flags[name] = shift_flags.get(name, 0) + 1
        print(json.dumps({label: per_source[label]}, default=str), flush=True)

    verdicts = [judge(per_source, name) for name in names[2:]]
    totals: dict[str, dict[str, float]] = {}
    for run in runs:
        t = totals.setdefault(run["variant"], {"seconds": 0.0, "cost_usd": 0.0, "prompt_tokens": 0, "thinking_tokens": 0, "errors": 0})
        t["seconds"] += run["seconds"]; t["cost_usd"] += run["cost_usd"]
        t["prompt_tokens"] += run["prompt_tokens"]; t["thinking_tokens"] += run["thinking_tokens"]
        t["errors"] += 1 if run["error"] else 0
    report = {"sources": [Path(v).name for v in videos], "variants": names, "verdicts": verdicts,
              "totals": totals, "timeline_shift_suspected": shift_flags, "per_source": per_source, "runs": runs,
              "rule": f"IoU>={IOU_MATCH}; variant passes if recall and top(score>={TOP_SCORE}) recall are within "
                      f"{NOISE_TOLERANCE} of the control-vs-control noise floor and athlete counts match"}
    (out / "ab_results.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    base_cost = totals.get("control", {}).get("cost_usd") or 0.0
    lines = ["## A/B: action selection vs control", "",
             "| variant | verdict | recall | top recall | cost vs control | time vs control |", "|---|---|---|---|---|---|"]
    for v in verdicts:
        t = totals.get(v["variant"], {})
        fmt = lambda x: "n/a" if x is None else f"{x:.2f}"
        cost = f"{(t.get('cost_usd', 0) / base_cost - 1) * 100:+.0f}%" if base_cost else "n/a"
        secs = totals.get("control", {}).get("seconds") or 0
        time_delta = f"{(t.get('seconds', 0) / secs - 1) * 100:+.0f}%" if secs else "n/a"
        lines.append(f"| {v['variant']} | **{v['verdict']}** | {fmt(v['result']['recall'])} (noise {fmt(v['noise_floor']['recall'])}) "
                     f"| {fmt(v['result']['top_recall'])} (noise {fmt(v['noise_floor']['top_recall'])}) | {cost} | {time_delta} |")
    if shift_flags:
        lines += ["", f"⚠️ Trim variants returned times relative to the trimmed clip on {shift_flags} source(s) — timeline NOT preserved."]
    lines += ["", f"Sources: {len(videos)} · {report['rule']}"]
    summary = "\n".join(lines)
    (out / "ab_summary.md").write_text(summary, encoding="utf-8")
    print(summary, flush=True)
    step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
