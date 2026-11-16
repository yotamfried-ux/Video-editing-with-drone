#!/usr/bin/env python3
"""Action start / end verification against the frozen GT (EVALUATION ONLY; verdict JSON out, never media).

Product rules (owner, cycle 5):
  start = the paddle-in that leads directly to catching THIS wave (not waiting, not unrelated paddling, not just the stand-up)
  end   = the end of the ride itself (fall, kick-out, exit, wave dies) - NOT the end of tracking.
Method: for every GT ride, the pipeline's own selected window for that ride is the candidate (never the GT). A clip
[candidate_start - PAD_BEFORE, candidate_end + PAD_AFTER] is cut from the compressed processed proxy in this process
(low resolution, no audio), together with a contact sheet of the target surfer, and the model returns the start of the
paddle-in, the take-off and the end of the ride in clip seconds. Errors are measured against GT-v1 per ride. Split by
athlete exactly like the identity experiment (prompt tuned on dev only; holdout run once).

usage: boundary_experiment.py --diagnostics DIR --out FILE --split dev|holdout [--budget-usd 0.3] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))
import gt_scorecard as sc  # noqa: E402
from identity_pair_experiment import Budget, MODEL, _sheet, appearance_crops, athlete_split, build_appearances, parse_json  # noqa: E402

PAD_BEFORE_SEC = 12.0
PAD_AFTER_SEC = 6.0
CLIP_FPS = 5
TOLERANCE_SEC = 0.5

BOUNDARY_PROMPT = """\
Image 0 is a contact sheet of crops of the TARGET surfer (different moments, from a drone). The video is a short drone clip
of a surf session that may show several surfers; it was cut around one candidate ride of the TARGET surfer.
Find that one ride and report, in SECONDS FROM THE START OF THE CLIP:
- paddle_start: when the TARGET begins the paddling that leads directly to catching THIS wave. Sitting or waiting on the board,
  drifting, or paddling that does not lead to this wave is NOT part of it. If the clip already opens on the TARGET paddling for
  this wave, answer 0.
- takeoff: when the TARGET stands up and starts riding the wave.
- ride_end: when the ride itself ends - the TARGET falls, kicks out, steps off the board, or the wave is over and the TARGET is
  no longer riding it. Paddling, swimming or walking that follows is NOT part of the ride, even if the TARGET stays visible.
- ride_end_kind: one of "fall", "kick_out", "exit", "wave_over", "unclear".
Use only what you can see. If the TARGET does not ride a wave in the clip, return {"ride": false}.
Return ONLY JSON: {"ride": true, "paddle_start": 0.0, "takeoff": 0.0, "ride_end": 0.0, "ride_end_kind": "fall",
"evidence": "short visual reason for start and end"}"""


# ------------------------------------------------------------------ pure logic (unit-tested)
def clip_window(cand_start: float, cand_end: float, duration: float | None = None) -> tuple[float, float]:
    a = max(0.0, cand_start - PAD_BEFORE_SEC)
    b = cand_end + PAD_AFTER_SEC
    if duration is not None:
        b = min(b, duration)
    return round(a, 3), round(max(b, a + 1.0), 3)


def parse_boundaries(raw: str, clip_len: float) -> dict[str, Any] | None:
    """Strict: finite numbers inside the clip, start <= takeoff <= end. Anything else is None (never a guessed time)."""
    obj = parse_json(raw)
    if not isinstance(obj, dict) or obj.get("ride") is not True:
        return None
    try:
        start, takeoff, end = float(obj["paddle_start"]), float(obj["takeoff"]), float(obj["ride_end"])
    except (KeyError, TypeError, ValueError):
        return None
    vals = (start, takeoff, end)
    if any(v != v or v in (float("inf"), float("-inf")) for v in vals):
        return None
    if not (0.0 <= start <= takeoff <= end <= clip_len + 0.5):
        return None
    return {"paddle_start": start, "takeoff": takeoff, "ride_end": end, "kind": str(obj.get("ride_end_kind", "unclear")),
            "evidence": str(obj.get("evidence", ""))[:200]}


def boundary_errors(verified: dict[str, Any], clip_offset: float, ride_start_sec: float, ride_end_sec: float) -> dict[str, float]:
    s, e = clip_offset + verified["paddle_start"], clip_offset + verified["ride_end"]
    return {"start_sec": round(s, 2), "end_sec": round(e, 2), "start_err": round(s - ride_start_sec, 2),
            "end_err": round(e - ride_end_sec, 2)}


def summarize(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    errs_s = [abs(r[key]["start_err"]) for r in rows if r.get(key)]
    errs_e = [abs(r[key]["end_err"]) for r in rows if r.get(key)]
    both = errs_s + errs_e

    def q(v, p):
        return round(sorted(v)[min(len(v) - 1, int(p * len(v)))], 2) if v else None
    return {"rides": len(rows), "evaluated": len(errs_s), "within_tol_start": sum(e <= TOLERANCE_SEC for e in errs_s),
            "within_tol_end": sum(e <= TOLERANCE_SEC for e in errs_e),
            "start_p50": q(errs_s, 0.5), "start_max": round(max(errs_s), 2) if errs_s else None,
            "end_p50": q(errs_e, 0.5), "end_max": round(max(errs_e), 2) if errs_e else None,
            "both_within_tol": sum(1 for r in rows if r.get(key) and abs(r[key]["start_err"]) <= TOLERANCE_SEC
                                   and abs(r[key]["end_err"]) <= TOLERANCE_SEC),
            "all_p95": q(both, 0.95)}


# ------------------------------------------------------------------ media (in memory / job temp only)
def _cut(video: str, a: float, b: float, tmp: str) -> bytes:
    out = os.path.join(tmp, "clip.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-i", video, "-t", f"{b - a:.3f}", "-an",
                    "-vf", "scale=-2:360,fps=10", "-c:v", "libx264", "-crf", "30", "-preset", "veryfast", out],
                   check=True, timeout=300)
    return Path(out).read_bytes()


def _duration(video: str) -> float:
    res = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                         capture_output=True, text=True, timeout=60)
    try:
        return float(res.stdout.strip())
    except ValueError:
        return 0.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--split", choices=["dev", "holdout"], required=True)
    ap.add_argument("--budget-usd", type=float, default=0.3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    gt = json.loads(sc.DEFAULT_GT.read_text(encoding="utf-8"))
    manifest = json.loads((args.diagnostics / "publishable_reel_manifest.json").read_text(encoding="utf-8"))
    truth = sc.load_gt(gt)
    apps = build_appearances(gt, manifest)
    dev_ath, hold_ath = athlete_split([a["athlete_id"] for a in apps])
    athletes = dev_ath if args.split == "dev" else hold_ath

    jobs = []
    for sha, src in truth.items():
        fps = src["fps"]
        for r in src["rides"]:
            if r["athlete_id"] not in athletes:
                continue
            cands = [a for a in apps if a["source_sha256"] == sha and a["athlete_id"] == r["athlete_id"]]
            best = max(cands, key=lambda a: sc._overlap(int(a["window_sec"][0] * fps), int(a["window_sec"][1] * fps),
                                                        r["start_frame"], r["end_frame"]), default=None)
            if best is None or sc._overlap(int(best["window_sec"][0] * fps), int(best["window_sec"][1] * fps),
                                           r["start_frame"], r["end_frame"]) <= 0:
                jobs.append({"ride_uid": r["ride_uid"], "skip": "no_pipeline_candidate"})
                continue
            jobs.append({"ride_uid": r["ride_uid"], "sha": sha, "app": best, "gt_start": r["start_frame"] / fps,
                         "gt_end": r["end_frame"] / fps,
                         "pipeline": {"start_err": round(best["window_sec"][0] - r["start_frame"] / fps, 2),
                                      "end_err": round(best["window_sec"][1] - r["end_frame"] / fps, 2)}})
    print(f"split={args.split} rides={len(jobs)} with_candidate={sum('skip' not in j for j in jobs)}")
    if args.dry_run:
        return 0

    from google import genai
    from google.genai import types
    from pipeline.r2_batch_restore import processed_key_for
    from integrations import r2_storage
    import urllib.parse
    import urllib.request

    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    q = urllib.parse.urlencode({"batch_id": f"eq.{os.environ['BATCH_ID']}", "removed_at": "is.null", "superseded_at": "is.null",
                                "select": "storage_key,content_sha256"})
    req = urllib.request.Request(f"{base}/rest/v1/source_uploads?{q}", headers={"apikey": key, "Authorization": f"Bearer {key}"})
    key_of = {r["content_sha256"]: r["storage_key"] for r in json.loads(urllib.request.urlopen(req, timeout=30).read())}
    sidecars = {}
    for f in (args.diagnostics / "sidecars").glob("*.perception.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        sidecars[d.get("source_sha256")] = d
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    budget = Budget(args.budget_usd)
    rows, latencies = [], []
    with tempfile.TemporaryDirectory(prefix="bnd-") as tmp:
        videos: dict[str, str] = {}
        for job in jobs:
            row = {"ride_uid": job["ride_uid"], "gt_start": round(job.get("gt_start", 0), 2), "gt_end": round(job.get("gt_end", 0), 2)}
            if "skip" in job:
                rows.append(dict(row, skip=job["skip"]))
                continue
            sha, app = job["sha"], job["app"]
            row["pipeline"] = job["pipeline"]
            try:
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
                dur = _duration(videos[sha])
                a, b = clip_window(app["window_sec"][0], app["window_sec"][1], dur or None)
                crops = appearance_crops(app, sidecars[sha], videos[sha], tmp, 6)
                if len(crops) < 3:
                    rows.append(dict(row, skip="too_few_target_crops"))
                    continue
                clip = _cut(videos[sha], a, b, tmp)
                if not budget.can():
                    rows.append(dict(row, skip="budget_cap"))
                    continue
                t0 = time.time()
                response = client.models.generate_content(
                    model=MODEL, config=types.GenerateContentConfig(temperature=0),
                    contents=[types.Part.from_bytes(data=_sheet(crops, 3), mime_type="image/jpeg"),
                              types.Part(inline_data=types.Blob(data=clip, mime_type="video/mp4"),
                                         video_metadata=types.VideoMetadata(fps=CLIP_FPS)),
                              BOUNDARY_PROMPT])
                latencies.append(round(time.time() - t0, 1))
                budget.add(getattr(response, "usage_metadata", None))
                text = getattr(response, "text", "") or ""
                parsed = parse_boundaries(text, b - a)
                row.update(clip=[a, b], clip_bytes=len(clip), raw_sha_len=len(text))
                if parsed is None:
                    row["verifier"] = None
                    row["raw_excerpt"] = text[:160]
                else:
                    row["verifier"] = boundary_errors(parsed, a, job["gt_start"], job["gt_end"])
                    row["kind"] = parsed["kind"]
                    row["evidence"] = parsed["evidence"]
                    row["takeoff_sec"] = round(a + parsed["takeoff"], 2)
            except Exception as exc:                    # one unreadable clip must not void the experiment
                row["skip"] = f"error:{type(exc).__name__}"
            rows.append(row)
    ev = [r for r in rows if "skip" not in r]
    report = {"schema": "sportreel.boundary_experiment.v1", "split": args.split, "model": MODEL, "media_in_result": False,
              "clip": {"pad_before": PAD_BEFORE_SEC, "pad_after": PAD_AFTER_SEC, "fps": CLIP_FPS},
              "pipeline": summarize([dict(r, p=r["pipeline"]) for r in ev], "p"),
              "verifier": summarize(ev, "verifier"),
              "cost": {"calls": budget.calls, "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out,
                       "estimated_usd": round(budget.spent, 4), "cap_usd": args.budget_usd,
                       "mean_latency_sec": round(sum(latencies) / len(latencies), 1) if latencies else None},
              "rides": rows}
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("pipeline", "verifier", "cost")}))
    for r in rows:
        print("RIDE " + json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
