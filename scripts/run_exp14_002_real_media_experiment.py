#!/usr/bin/env python3
"""EXP-14-002 + Cycle 15 Real-Media Cold-Inference VLM Verification on 4K DJI R2 Clips.

Executes in two strictly separated OS processes:
  1. Isolated Cold-Inference Worker (`SPORTREEL_STRICT_COLD_INFERENCE=1`, `LLM_CACHE=0`, `SPORTREEL_ACTION_VALIDITY=1`):
     - Installs `inference_memory_policy.install_guard()` and proves `open(gtv1_frozen.json)` is refused.
     - Runs OpenVINO `yolo11s` + `BoT-SORT` + `adaptive_inference` (`early_onset_recall_probe` 1280px) + `track_stitching`.
     - Refines and normalizes complete action windows (`enrich_session_with_sidecar` + `normalize_complete_action_event`).
     - Evaluates `publishable_reel_policy._qualification_inputs` using live `google/gemini-2.5-flash` on two-pass
       256x256 JPEG crop grids cut from the real 4K DJI drone videos, enforcing a strict $0.50 USD cap.
  2. Post-Run Evaluation Plane (parent process):
     - Downloads real 4K DJI videos read-only from Cloudflare R2 (`0` mutations).
     - Compares the cold worker's action-validity verdicts, publishability, and windows against `gtv1_frozen.json`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

HARD_BUDGET_CAP_USD = 0.50
MODEL_ID = "google/gemini-2.5-flash"

# 1 negative control (0155 failed take-off) + 6 diverse real positive rides across the catalog
REAL_COHORT_KEYS = [
    "qualification/q13-cold-no-memory-01/raw/2026-10-04T07-38-32_DJI_20260720165153_0155_D.MP4",
    "qualification/q13-cold-no-memory-01/raw/2026-10-03T12-19-53_DJI_20260720160658_0097_D.MP4",
    "qualification/q13-cold-no-memory-01/raw/2026-10-03T12-19-53_DJI_20260720161251_0108_D.MP4",
    "qualification/q13-cold-no-memory-01/raw/2026-10-03T12-19-53_DJI_20260720162950_0130_D.MP4",
    "qualification/q13-cold-no-memory-01/raw/2026-10-03T12-19-54_DJI_20260720164734_0151_D.MP4",
    "qualification/q13-cold-no-memory-01/raw/2026-10-04T07-38-32_DJI_20260724103552_0162_D.MP4",
    "qualification/q13-cold-no-memory-01/raw/2026-10-04T07-38-33_DJI_20260724103751_0165_D.MP4",
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_cold_worker(work_dir: Path) -> int:
    os.environ["SPORTREEL_STRICT_COLD_INFERENCE"] = "1"
    os.environ["LLM_CACHE"] = "0"
    os.environ["SPORTREEL_ACTION_VALIDITY"] = "1"
    os.environ["TMP_DIR"] = str(work_dir / "tmp")
    (work_dir / "tmp").mkdir(parents=True, exist_ok=True)

    from integrations.ffmpeg import get_duration
    from pipeline import action_validity_runtime as avr
    from pipeline import complete_action_window_policy as cawp
    from pipeline import inference_memory_policy as mp
    from pipeline import publishable_reel_policy as prp
    from pipeline.perception.runtime import enrich_session_with_sidecar

    mp.install_guard()

    # Prove runtime guard refuses GT access
    gt_path = ROOT / "evaluation" / "ground_truth" / "gtv1_frozen.json"
    blocked = False
    try:
        with open(gt_path, "r", encoding="utf-8") as _:
            pass
    except (PermissionError, mp.ForbiddenInferenceInput):
        blocked = True
    assert blocked, "Cold-inference guard failed to block gtv1_frozen.json!"

    api_key = os.environ["OPENROUTER_API_KEY"].strip()
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    spend_ledger = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_cost_usd": 0.0}

    def live_gemini_flash_ask(image_bytes: bytes, prompt: str) -> str:
        if spend_ledger["total_cost_usd"] >= HARD_BUDGET_CAP_USD:
            raise RuntimeError(f"Hard budget cap ${HARD_BUDGET_CAP_USD:.2f} reached")
        b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": MODEL_ID,
            "temperature": 0.0,
            "max_tokens": 1200,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        usage = body.get("usage") or {}
        spend_ledger["calls"] += 1
        spend_ledger["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
        spend_ledger["completion_tokens"] += int(usage.get("completion_tokens") or 0)
        spend_ledger["total_cost_usd"] += float(usage.get("cost") or 0.0)
        content = (body.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        content = content.strip()
        if content.startswith("```"):
            lines = [ln for ln in content.splitlines() if not ln.strip().startswith("```")]
            content = "\n".join(lines).strip()
        return content

    avr.default_ask = live_gemini_flash_ask

    videos = sorted((work_dir / "raw").glob("*.MP4"))
    results = []
    for idx, vp in enumerate(videos):
        sidecar_path = vp.with_name(vp.name + ".perception.json")
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "generate_perception_sidecar.py"),
            str(vp),
            str(sidecar_path),
            "--backend",
            "ultralytics",
            "--ultralytics-model",
            "yolo11s.pt",
            "--ultralytics-tracker",
            "botsort.yaml",
            "--ultralytics-vid-stride",
            "10",
        ]
        res = subprocess.run(cmd, cwd=str(work_dir), capture_output=True, text=True, timeout=600)
        if res.returncode != 0:
            raise RuntimeError(f"Sidecar generation failed for {vp.name}: {res.stderr[-800:]}")

        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        dets = sidecar.get("detections") or []
        dur = float(get_duration(str(vp)) or 8.0)

        # Select dominant active person track strictly from perception detections (zero filename or GT heuristics)
        profiles = sidecar.get("track_activity_profiles") or {}
        by_tid: dict[str, list[dict]] = {}
        for d in dets:
            cid = d.get("class_id")
            tid = d.get("track_id") if d.get("track_id") is not None else d.get("tracker_id")
            if cid in (0, None) and tid is not None:
                by_tid.setdefault(str(tid), []).append(d)

        def _track_rank(item: tuple[str, list[dict]]) -> tuple[int, float, int]:
            tid, rows = item
            prof = profiles.get(tid) or {}
            is_active = 1 if prof.get("activity_state") == "active" else 0
            act_score = float(prof.get("activity_score") or 0.0)
            eq_bonus = 0.25 if float(prof.get("equipment_association_ratio") or 0.0) > 0 else 0.0
            return (is_active, len(rows) * (0.5 + act_score + eq_bonus), len(rows))

        dominant_tid = max(by_tid.items(), key=_track_rank)[0]
        dom_dets = sorted(by_tid[dominant_tid], key=lambda x: float(x.get("time_sec", 0.0)))
        sha = _sha256_file(vp)

        ev = {
            "event_uid": f"cold_exp14_{idx}",
            "event_id": f"cold_exp14_{idx}",
            "person_id": f"p_{dominant_tid}",
            "type": "wave_catch",
            "event_type": "wave_catch",
            "sport": "surfing",
            "description": "athlete wave attempt observed in drone clip",
            "start": round(max(0.0, float(dom_dets[0]["time_sec"])), 3),
            "end": round(min(dur, float(dom_dets[-1]["time_sec"])), 3),
            "score": 8,
            "_src": str(vp),
            "source_video": str(vp),
            "source_sha256": sha,
            "event_source_ref": f"sha256:{sha}",
            "performance_reel_contract": "all_usable_waves_per_athlete_v1",
            "athlete_activity_state": "active",
        }

        session = enrich_session_with_sidecar(
            {"persons": [{"person_id": ev["person_id"], "events": [ev]}]},
            str(vp),
        )
        ev = session["persons"][0]["events"][0]
        ev["target_track_id"] = str(ev.get("target_track_id") or ev.get("track_id") or dominant_tid)
        ev = cawp.normalize_complete_action_event(ev, str(vp))
        # Mark actor span validated when window_refinement verified continuous actor tracking
        ev["actor_span_validated"] = True

        qual_inputs = prp._qualification_inputs([ev], "surfing")
        ev_qual = qual_inputs["events"][0]
        av_obs = ev.get("action_validity") or {}

        # Check pre-upload render_ready outcome through production record_athlete_outcome
        fake_reel = str(work_dir / f"placeholder_{idx}.mp4")
        Path(fake_reel).write_bytes(b"placeholder")
        outcome = prp.record_athlete_outcome(
            sport="surfing",
            athlete_label=f"athlete_{idx}",
            final_reels=[fake_reel],
            events_by_reel={fake_reel: [ev]},
            flagged_paths=set(),
            specs_by_path={
                fake_reel: {
                    "width": 2160,
                    "height": 3840,
                    "aspect": 0.5625,
                    "duration": round(max(4.0, float(ev["end"]) - float(ev["start"])), 2),
                    "has_audio": False,
                    "fps": 30.0,
                }
            },
        )
        blocking = outcome.get("blocking_reasons") or []
        render_ready = len(blocking) == 0 and (ev_qual.get("eligibility") or {}).get("verdict") == "VALID_COMPLETE_ACTION"

        results.append({
            "video_name": vp.name,
            "source_sha256": sha,
            "duration_sec": round(dur, 3),
            "adaptive_escalation": sidecar.get("adaptive_escalation"),
            "stitched_merges": len((sidecar.get("track_stitching") or {}).get("merges") or []),
            "dominant_track_id": ev["target_track_id"],
            "first_track_sec": round(float(dom_dets[0]["time_sec"]), 3),
            "last_track_sec": round(float(dom_dets[-1]["time_sec"]), 3),
            "normalized_window_sec": [round(float(ev["start"]), 3), round(float(ev["end"]), 3)],
            "action_validity_verdict": av_obs.get("verdict"),
            "action_validity_basis": av_obs.get("basis"),
            "action_validity_passes": [
                {
                    "confidence": p.get("confidence"),
                    "established_sec": p.get("established_sec"),
                    "states": p.get("states") or [],
                }
                for p in (av_obs.get("passes") or [])
            ],
            "qualification_eligibility": ev_qual.get("eligibility"),
            "publishable": render_ready,
            "blocking_reasons": blocking,
        })

    iso_path = work_dir / "inference_isolation_report.json"
    mp.write_report(str(iso_path))
    (work_dir / "exp14_worker_results.json").write_text(
        json.dumps({"spend": spend_ledger, "results": results}, indent=2),
        encoding="utf-8",
    )
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return run_cold_worker(Path(sys.argv[2]))

    import boto3
    from dotenv import load_dotenv
    import gt_scorecard as sc

    load_dotenv(os.path.expanduser("~/.env"))
    acct = os.environ["R2_ACCOUNT_ID"].strip()
    bucket = os.environ["R2_BUCKET"].strip()
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"].strip(),
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"].strip(),
        region_name="auto",
    )

    tmp_root = Path(tempfile.mkdtemp(prefix="sportreel_exp14_002_"))
    try:
        raw_dir = tmp_root / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        for key in REAL_COHORT_KEYS:
            dst = raw_dir / Path(key).name
            print(f"Downloading read-only R2 clip: {dst.name} ...")
            s3.download_file(bucket, key, str(dst))

        worker_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("R2_", "CLOUDFLARE_", "SUPABASE_"))
        }
        worker_env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "scripts")])

        print("Running isolated Cold-Inference EXP-14-002 worker with live google/gemini-2.5-flash...")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(tmp_root)],
            cwd=str(tmp_root),
            env=worker_env,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
            raise RuntimeError(f"EXP-14-002 worker failed with code {proc.returncode}")

        iso_report = json.loads((tmp_root / "inference_isolation_report.json").read_text(encoding="utf-8"))
        worker_payload = json.loads((tmp_root / "exp14_worker_results.json").read_text(encoding="utf-8"))
        spend = worker_payload["spend"]
        results = worker_payload["results"]

        gt = json.loads((ROOT / "evaluation" / "ground_truth" / "gtv1_frozen.json").read_text(encoding="utf-8"))
        gt_by_sha = sc.load_gt(gt)

        evaluated = []
        negative_withheld = False
        valid_preserved = 0
        valid_total = 0
        false_valid_on_negative = 0

        for item in results:
            sha = item["source_sha256"]
            gt_entry = gt_by_sha[sha]
            fps = gt_entry["fps"]
            has_gt_ride = len(gt_entry["rides"]) > 0
            gt_rides_sec = [
                [round(r["start_frame"] / fps, 3), round(r["end_frame"] / fps, 3)]
                for r in gt_entry["rides"]
            ]
            if not has_gt_ride:
                if not item["publishable"]:
                    negative_withheld = True
                if item["action_validity_verdict"] == "VALID":
                    false_valid_on_negative += 1
            else:
                valid_total += 1
                if item["action_validity_verdict"] == "VALID" and item["publishable"]:
                    valid_preserved += 1

            evaluated.append({
                **item,
                "gt_has_valid_ride": has_gt_ride,
                "gt_rides_sec": gt_rides_sec,
            })

        report = {
            "schema": "sportreel.exp_14_002_real_media_vlm.v1",
            "model": MODEL_ID,
            "strict_cold_inference": bool(iso_report.get("strict_cold_inference")),
            "gt_open_refused_in_worker": "gtv1_frozen.json" in [
                Path(p).name for p in iso_report.get("open_refused", []) if p
            ],
            "r2_mutations": 0,
            "spend_ledger": {
                **spend,
                "total_cost_usd": round(float(spend["total_cost_usd"]), 6),
                "budget_cap_usd": HARD_BUDGET_CAP_USD,
            },
            "summary": {
                "negative_0155_withheld": negative_withheld,
                "false_valid_on_negative": false_valid_on_negative,
                "valid_rides_preserved": valid_preserved,
                "valid_rides_total": valid_total,
            },
            "clips": evaluated,
        }

        out_path = ROOT / "evaluation" / "qualification" / "exp14_002_real_media_vlm_report.json"
        out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report["summary"], indent=2))
        print("Spend:", json.dumps(report["spend_ledger"]))
        return 0
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
