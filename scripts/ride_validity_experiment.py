#!/usr/bin/env python3
"""EXP-08-001: ride-validity verifier (pipeline/ride_validity.py) on real clips, scored against frozen GT-v1.

EVALUATION ONLY. Calls the PRODUCTION prompt / parser / decision (`ride_validity.verify_window`) with a capped Gemini
client. Media: compressed proxies from R2 (read-only), cut in the job temp dir; the result artifact is JSON only.

Jobs
  A  every selected output window of the diagnostics run (target = the window's bound track), asked REPS times with
     no verdict cache, to measure stability.
  B  GT controls (target chosen by GT box containment - evaluation only): each excluded GT segment and the 0094 tail
     after A's GT end, to observe the verdict and the reported ride end.
Scoring (pre-registered, before any call):
  label valid    window frames of its primary GT athlete are mostly GT include
  label invalid  window frames mostly in a GT exclude segment whose event_type is failed_takeoff
  label other    everything else (uncatalogued target, exclude for other reasons): reported, not scored
  FP  = valid window rejected (would delete a ride)        -> failure condition: any FP
  TP  = invalid window rejected                              -> success condition: 0155 rejected in every rep
  stability = same decision in every rep for each window
Cost: model tokens recorded per call; hard cap --budget-usd; stops before a call that could exceed it.

usage: ride_validity_experiment.py --diagnostics DIR (--gt-boxes FILE --jobs-out FILE | --jobs FILE) --out FILE --budget-usd 0.8 [--reps 2] [--dry-run]
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
from pipeline import ride_validity as rv  # noqa: E402

PAD_SEC = 0.5
CLIP_FPS = 4
MEDIA_RES = "MEDIA_RESOLUTION_LOW"


def interp(points, frame, max_gap=30):
    fr = [p[0] for p in points]
    i = bisect.bisect_left(fr, frame)
    if i < len(fr) and fr[i] == frame:
        return points[i][1:5]
    if i == 0 or i == len(points) or points[i][0] - points[i - 1][0] > max_gap:
        return None
    t = (frame - points[i - 1][0]) / (points[i][0] - points[i - 1][0])
    return [points[i - 1][k] + t * (points[i][k] - points[i - 1][k]) for k in range(1, 5)]


def inside(a, b):
    ix = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return ix * iy / (a[2] * a[3]) if a[2] * a[3] else 0


def athlete_of_track(sc: dict, track: str, gt: dict, f0: int, f1: int) -> str | None:
    seg_ath = {s[5] for s in gt["segments"] if s[5]}
    votes: Counter = Counter()
    for d in sc["detections"]:
        if str(d.get("track_id")) != track or not (f0 <= d["frame_index"] <= f1):
            continue
        x0, y0, x1, y1 = d["bbox_xyxy"]
        W, H = d["frame_width"], d["frame_height"]
        b = [x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H]
        for t in gt["tracks"]:
            g = interp(t["points"], d["frame_index"])
            aid = t["athlete_id"] or (next(iter(seg_ath)) if len(seg_ath) == 1 else None)
            if g and aid and inside(b, g) >= 0.5:
                votes[aid] += 1
    return votes.most_common(1)[0][0] if votes else None


def label(gt: dict, athlete: str | None, f0: int, f1: int) -> tuple[str, dict]:
    if athlete is None:
        return "other", {"why": "target not a GT athlete"}
    c: Counter = Counter()
    for f in range(f0, f1 + 1, 6):
        hits = [s for s in gt["segments"] if s[0] <= f <= s[1] and s[5] == athlete]
        if any(s[2] == "exclude" for s in hits):
            c["exclude_" + next(s[6] for s in hits if s[2] == "exclude")] += 1
        elif hits:
            c["include"] += 1
        else:
            c["none"] += 1
    n = sum(c.values()) or 1
    if c["include"] / n >= 0.5:
        return "valid", dict(c)
    if c["exclude_failed_takeoff"] / n >= 0.5:
        return "invalid", dict(c)
    return "other", dict(c)


def build_jobs(diag: Path, gt_boxes: dict) -> list[dict]:
    pred = json.loads((diag / "predictions.v1.json").read_text())
    side = {}
    for p in (diag / "sidecars").glob("*.perception.json"):
        d = json.loads(p.read_text())
        side[d["source_sha256"]] = d
    jobs = []
    for src in pred["sources"]:
        sha, fps = src["source_sha256"], src.get("fps") or 59.94
        gt, sc = gt_boxes.get(sha), side.get(sha)
        if not gt or not sc:
            continue
        for ev in src["events"]:
            if ev["decision"] != "selected":
                continue
            for out in ev["outputs"]:
                tid = str(out.get("track_id"))
                f0, f1 = int(ev["start_sec"] * fps), int(ev["end_sec"] * fps)
                ath = athlete_of_track(sc, tid, gt, f0, f1)
                lab, detail = label(gt, ath, f0, f1)
                jobs.append({"kind": "A_selected_window", "sha": sha, "source": src["source_video"], "track_id": tid,
                             "window_sec": [ev["start_sec"], ev["end_sec"]], "gt_athlete": ath, "label": lab,
                             "label_detail": detail, "fps": fps,
                             "gt_end_sec": max((s[1] / fps for s in gt["segments"] if s[5] == ath and s[2] == "include"
                                                and s[0] <= f1 and s[1] >= f0), default=None)})
        # B: excluded GT segments and every GT athlete's tail after its last include, target by GT containment
        for s in gt["segments"]:
            if s[2] != "exclude":
                continue
            tid = best_track_for_athlete(sc, gt, s[5], s[0], s[1])
            if tid:
                jobs.append({"kind": "B_gt_exclude_segment", "sha": sha, "source": src["source_video"], "track_id": tid,
                             "window_sec": [s[0] / fps, s[1] / fps], "gt_athlete": s[5],
                             "label": "invalid" if s[6] == "failed_takeoff" else "other",
                             "label_detail": {"event_type": s[6], "reasons": s[4]}, "fps": fps})
    return jobs


def best_track_for_athlete(sc: dict, gt: dict, athlete: str, f0: int, f1: int) -> str | None:
    seg_ath = {s[5] for s in gt["segments"] if s[5]}
    tr = [t for t in gt["tracks"] if (t["athlete_id"] or (next(iter(seg_ath)) if len(seg_ath) == 1 else None)) == athlete]
    if not tr:
        return None
    votes: Counter = Counter()
    for d in sc["detections"]:
        if d.get("class_name") != "person" or not (f0 <= d["frame_index"] <= f1):
            continue
        g = interp(tr[0]["points"], d["frame_index"])
        if not g:
            continue
        x0, y0, x1, y1 = d["bbox_xyxy"]
        W, H = d["frame_width"], d["frame_height"]
        if inside([x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H], g) >= 0.5:
            votes[str(d.get("track_id"))] += 1
    return votes.most_common(1)[0][0] if votes else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", required=True, type=Path)
    ap.add_argument("--gt-boxes", type=Path, help="private GT boxes (local only): builds the labelled job list")
    ap.add_argument("--jobs", type=Path, help="committed labelled job list (CI): no GT boxes needed")
    ap.add_argument("--jobs-out", type=Path, help="write the labelled job list and exit")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--budget-usd", type=float, default=0.8)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--extra", default="", help="extra B windows 'SUFFIX:start:end:label;...' (e.g. the 0094 tail)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.jobs:
        jobs = json.loads(a.jobs.read_text())["jobs"]
    else:
        jobs = build_jobs(a.diagnostics, json.loads(a.gt_boxes.read_text()))
    for spec in [x for x in a.extra.split(";") if x.strip()]:
        suffix, s0, s1, lab = spec.split(":")
        base = next((j for j in jobs if j["source"].endswith(suffix) and j["kind"] == "A_selected_window"), None)
        if base:
            jobs.append({**base, "kind": "B_extra", "window_sec": [float(s0), float(s1)], "label": lab,
                         "label_detail": {"extra": spec}})
    print(f"jobs={len(jobs)} labels={dict(Counter(j['label'] for j in jobs))}")
    for j in jobs:
        print("JOB", j["kind"], j["source"][-11:-4], j["track_id"], j["window_sec"], j["label"])
    if a.jobs_out:
        a.jobs_out.write_text(json.dumps({"experiment": "EXP-08-001", "diagnostics_run": a.diagnostics.name,
                                          "labels_from": "GT-v1 frozen ae844a94 (labels only; no boxes)", "jobs": jobs}, indent=1))
        return 0
    if a.dry_run:
        return 0

    from google import genai
    from google.genai import types
    from identity_pair_experiment import MODEL, Budget, _sheet, appearance_crops
    from boundary_experiment import _cut, _duration
    from pipeline.r2_batch_restore import processed_key_for
    from integrations import r2_storage
    import urllib.parse
    import urllib.request

    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    q = urllib.parse.urlencode({"batch_id": f"eq.{os.environ['BATCH_ID']}", "removed_at": "is.null",
                                "superseded_at": "is.null", "select": "storage_key,content_sha256"})
    req = urllib.request.Request(f"{base}/rest/v1/source_uploads?{q}", headers={"apikey": key, "Authorization": f"Bearer {key}"})
    key_of = {r["content_sha256"]: r["storage_key"] for r in json.loads(urllib.request.urlopen(req, timeout=30).read())}
    sidecars = {}
    for f in (a.diagnostics / "sidecars").glob("*.perception.json"):
        d = json.loads(f.read_text())
        sidecars[d["source_sha256"]] = d
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    budget = Budget(a.budget_usd)
    model_versions: Counter = Counter()
    rows = []

    def ask_factory(row):
        def ask(clip, sheet, prompt):
            if not budget.can():
                raise RuntimeError("budget_cap")
            t0 = time.time()
            resp = client.models.generate_content(
                model=MODEL,
                config=types.GenerateContentConfig(temperature=0, media_resolution=MEDIA_RES),
                contents=[types.Part.from_bytes(data=sheet, mime_type="image/jpeg"),
                          types.Part(inline_data=types.Blob(data=clip, mime_type="video/mp4"),
                                     video_metadata=types.VideoMetadata(fps=CLIP_FPS)),
                          prompt])
            u = getattr(resp, "usage_metadata", None)
            before = budget.spent
            budget.add(u)
            model_versions[getattr(resp, "model_version", None) or MODEL] += 1
            row.setdefault("calls", []).append({"latency_sec": round(time.time() - t0, 1),
                                                "usd": round(budget.spent - before, 5),
                                                "tokens_in": int(getattr(u, "prompt_token_count", 0) or 0),
                                                "tokens_out": int(getattr(u, "candidates_token_count", 0) or 0)
                                                + int(getattr(u, "thoughts_token_count", 0) or 0)})
            return getattr(resp, "text", "") or ""
        return ask

    with tempfile.TemporaryDirectory(prefix="rv-") as tmp:
        videos: dict[str, str] = {}
        for job in jobs:
            reps = a.reps if job["kind"] == "A_selected_window" else 1
            for rep in range(reps):
                row = {k: job[k] for k in ("kind", "source", "track_id", "window_sec", "gt_athlete", "label", "label_detail")}
                row["rep"] = rep
                row["gt_end_sec"] = job.get("gt_end_sec")
                try:
                    sha = job["sha"]
                    if sha not in videos:
                        name = key_of[sha].rsplit("/", 1)[-1]
                        found = next((c for c in (processed_key_for(key_of[sha]), "processed/" + name, key_of[sha], "raw/" + name)
                                      if r2_storage._head(c) is not None), None)
                        if found is None:
                            rows.append(dict(row, skip="media_unavailable"))
                            continue
                        dest = os.path.join(tmp, f"{sha[:12]}.mp4")
                        r2_storage.download_object(found, dest)
                        videos[sha] = dest
                    dur = _duration(videos[sha]) or 1e9
                    c0, c1 = max(0.0, job["window_sec"][0] - PAD_SEC), min(dur, job["window_sec"][1] + PAD_SEC)
                    app = {"window_sec": job["window_sec"], "track_id": job["track_id"]}
                    crops = appearance_crops(app, sidecars[sha], videos[sha], tmp, 6)
                    if len(crops) < 3:
                        rows.append(dict(row, skip="too_few_target_crops"))
                        continue
                    clip = _cut(videos[sha], c0, c1, tmp)
                    res = rv.verify_window(clip, _sheet(crops, 3), ask_factory(row), model=MODEL, cache=None)
                    row.update(clip_sec=[round(c0, 2), round(c1, 2)], verdict=res["verdict"], decision=res["decision"])
                    v = res["verdict"]
                    if v and v.get("ride_end_sec") is not None:
                        row["ride_end_source_sec"] = round(c0 + v["ride_end_sec"], 2)
                except Exception as exc:
                    row["skip"] = f"error:{type(exc).__name__}:{str(exc)[:80]}"
                rows.append(row)
                if not budget.can():
                    break

    scored = [r for r in rows if "decision" in r and r["label"] in ("valid", "invalid")]
    fp = [r for r in scored if r["label"] == "valid" and not r["decision"]["keep"]]
    tp = [r for r in scored if r["label"] == "invalid" and not r["decision"]["keep"]]
    fn = [r for r in scored if r["label"] == "invalid" and r["decision"]["keep"]]
    by_window = defaultdict(set)
    for r in rows:
        if "decision" in r and r["kind"] == "A_selected_window":
            by_window[(r["source"], r["track_id"], tuple(r["window_sec"]))].add(r["decision"]["status"])
    ends = [r for r in rows if r.get("ride_end_source_sec") is not None and r.get("gt_end_sec") and r["label"] == "valid"]
    report = {
        "schema": "sportreel.ride_validity_experiment.v1", "experiment": "EXP-08-001",
        "executed_code_sha": os.environ.get("GITHUB_SHA"), "model": MODEL, "model_versions": dict(model_versions),
        "prompt_version": rv.PROMPT_VERSION, "decision_rule": {"min_standing_sec": rv.MIN_STANDING_SEC, "reject_only_confidence": "high"},
        "clip": {"pad_sec": PAD_SEC, "fps": CLIP_FPS, "media_resolution": MEDIA_RES}, "reps": a.reps,
        "gt": "GT-v1 frozen ae844a94 / b31fd9b4…27c9 (scoring only)", "media_in_result": False,
        "summary": {"rows": len(rows), "scored": len(scored), "false_positive_valid_rejected": len(fp),
                    "true_positive_invalid_rejected": len(tp), "false_negative_invalid_kept": len(fn),
                    "windows_stable": sum(1 for v in by_window.values() if len(v) == 1), "windows": len(by_window),
                    "status_counts": dict(Counter(r["decision"]["status"] for r in rows if "decision" in r)),
                    "ride_end_abs_err_sec": sorted(round(abs(r["ride_end_source_sec"] - r["gt_end_sec"]), 2) for r in ends)},
        "cost": {"calls": budget.calls, "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out,
                 "estimated_usd": round(budget.spent, 4), "cap_usd": a.budget_usd},
        "rows": rows}
    a.out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("summary", "cost", "model_versions")}))
    for r in rows:
        print("ROW " + json.dumps({k: r.get(k) for k in ("kind", "source", "track_id", "label", "rep", "decision", "verdict", "skip")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
