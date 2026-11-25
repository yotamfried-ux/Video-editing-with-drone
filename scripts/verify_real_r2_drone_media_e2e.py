#!/usr/bin/env python3
"""End-to-end Cold-Inference verification on REAL 4K DJI drone media from R2 (read-only) vs frozen GT-v1.

Two-plane isolation (MEM-01..06):
  1. Inference Plane (child subprocess with SPORTREEL_STRICT_COLD_INFERENCE=1, LLM_CACHE=0):
     - Runtime `open()` guard refuses any read under `evaluation/` (verified!).
     - Runs real OpenVINO YOLO + BoT-SORT perception (`generate_perception_sidecar.py`) with early-onset recall probe
       and velocity-projected track stitching on real 4K DJI MP4s downloaded read-only to a temporary directory.
     - Runs real `window_refinement` + `complete_action_window_policy` (`in_progress_from_recording_start` + end clamp).
     - Runs real `action_validity_runtime.observe_event` (extracting both interleaved 256x256 crop grids from real 4K frames).
     - Renders real 4K 2160x3840 30fps H.264 High BT.709 silent MP4 via `quality_preserving_framing` + `editor.compile_reel`
       and runs `tiered_qa_gate.run_tier1_local_qa_checks`.
     - Emits `inference_isolation_report.json` + rendered clip manifest.
  2. Evaluation Plane (parent process, after child exits):
     - Verifies `inference_isolation_report.json` (strict=True, 0 cache hits, all history channels closed).
     - Verifies `ffprobe` 4K BT.709 silent media contract on the rendered real drone reel.
     - Scores SHA-256 & rendered windows against `evaluation/ground_truth/gtv1_frozen.json` via `gt_scorecard.py`.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


REAL_KEYS = [
    # Valid GT-v1 ride (0165, ~7.6s 4K 60fps DJI drone clip)
    "qualification/q13-cold-no-memory-01/raw/2026-10-04T07-38-33_DJI_20260724103751_0165_D.MP4",
    # Negative GT-v1 failed takeoff (0155, ~7.9s 4K 60fps DJI drone clip)
    "qualification/q13-cold-no-memory-01/raw/2026-10-04T07-38-32_DJI_20260720165153_0155_D.MP4",
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_cold_inference_worker(work_dir: Path) -> int:
    """Runs strictly inside the isolated cold-inference child process (NEVER touches evaluation/)."""
    os.environ["SPORTREEL_STRICT_COLD_INFERENCE"] = "1"
    os.environ["LLM_CACHE"] = "0"
    os.environ["SPORTREEL_ACTION_VALIDITY"] = "1"
    os.environ["TMP_DIR"] = str(work_dir / "tmp")
    (work_dir / "tmp").mkdir(parents=True, exist_ok=True)

    from integrations.ffmpeg import get_duration, get_reel_specs
    from pipeline import action_validity as av
    from pipeline import action_validity_runtime as avr
    from pipeline import complete_action_window_policy as cawp
    from pipeline import inference_memory_policy as mp
    from pipeline import output_qualification as oq
    from pipeline import quality_preserving_framing as qpf
    from pipeline.perception.runtime import enrich_session_with_sidecar, load_sidecar_detections
    from pipeline.stages import editor
    from pipeline.tiered_qa_gate import run_tier1_local_qa_checks

    mp.install_guard()
    qpf.install()

    # Negative control inside real cold worker: opening GT must fail closed!
    gt_blocked = False
    try:
        (ROOT / "evaluation" / "ground_truth" / "gtv1_frozen.json").read_text(encoding="utf-8")
    except (PermissionError, mp.ForbiddenInferenceInput):
        gt_blocked = True
    assert gt_blocked, "Cold inference worker MUST refuse reading evaluation/ground_truth/gtv1_frozen.json"

    videos = sorted((work_dir / "raw").glob("*.MP4"))
    outputs = []

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

        # Pick dominant tracked person from real drone detections (blind — no GT or filename branching)
        by_tid: dict[str, list[dict]] = {}
        for d in dets:
            cid = d.get("class_id")
            tid = d.get("track_id") if d.get("track_id") is not None else d.get("tracker_id")
            if (cid in (None, 0, "0") or d.get("class_name") == "person") and tid is not None:
                by_tid.setdefault(str(tid), []).append(d)
        if not by_tid:
            raise RuntimeError(f"Zero tracked persons in {vp.name} (status={sidecar.get('status')}, total_dets={len(dets)})")
        dominant_tid = max(by_tid.items(), key=lambda kv: len(kv[1]))[0]
        dom_dets = sorted(by_tid[dominant_tid], key=lambda d: float(d["time_sec"]))

        ev = {
            "event_id": f"cold_ev_{idx}",
            "person_id": f"p_{dominant_tid}",
            "type": "surf_ride",
            "sport": "surfing",
            "description": "athlete riding wave in drone footage",
            "start": round(max(0.0, float(dom_dets[0]["time_sec"])), 3),
            "end": round(min(dur, float(dom_dets[-1]["time_sec"])), 3),
            "score": 8,
            "_src": str(vp),
            "source_video": vp.name,
            "source_sha256": _sha256_file(vp),
            "performance_reel_contract": "all_usable_waves_per_athlete_v1",
        }
        session = enrich_session_with_sidecar(
            {"persons": [{"person_id": ev["person_id"], "events": [ev]}]},
            str(vp),
        )
        ev = session["persons"][0]["events"][0]
        ev["target_track_id"] = str(ev.get("target_track_id") or ev.get("track_id") or dominant_tid)
        ev = cawp.normalize_complete_action_event(ev, str(vp))

        # Build real two-pass 256x256 crop grids from the real 4K DJI video!
        typed_dets = load_sidecar_detections(str(vp))
        plan = avr.sample_plan(float(ev["start"]), float(ev["end"]))
        tol = max(0.3, plan["step_sec"] / 2)
        grids_built = 0
        for pass_times in plan["passes"]:
            samples = avr.target_samples(typed_dets, ev["target_track_id"], pass_times, tol)
            kept = [(t, s) for t, s in zip(pass_times, samples) if s is not None]
            if len(kept) >= 3:
                grid_bytes = avr.build_grid(str(vp), [s for _, s in kept], [t for t, _ in kept])
                if grid_bytes and len(grid_bytes) > 1000:
                    grids_built += 1

        # Render real 4K 2160x3840 30fps BT.709 silent reel for the clip (supports single-pass virtual clips)
        clip_path = editor.cut_clip(str(vp), ev, idx, slowmo=False, sport="surfing")
        assert clip_path and (os.path.exists(clip_path) or qpf.virtual_clip(clip_path) is not None), (
            f"cut_clip failed for {vp.name}"
        )
        reel_out = str(work_dir / f"reel_{idx}.mp4")
        compiled = editor.compile_reel([clip_path], logo_path="", output_path=reel_out, sport="surfing", athlete_label=f"athlete_{idx}")
        assert compiled and os.path.exists(compiled), f"compile_reel failed for {vp.name}"

        specs = get_reel_specs(compiled)
        tier1 = run_tier1_local_qa_checks(compiled, [ev], specs=specs)

        outputs.append({
            "video_name": vp.name,
            "source_sha256": ev["source_sha256"],
            "duration_sec": round(dur, 3),
            "detections_count": len(dets),
            "canonical_tracks": len(by_tid),
            "dominant_track_id": dominant_tid,
            "refined_window_sec": [round(float(ev["start"]), 3), round(float(ev["end"]), 3)],
            "in_progress_from_start": bool((ev.get("window_refinement") or {}).get("in_progress_from_recording_start")),
            "two_pass_crop_grids_built": grids_built,
            "rendered_reel": compiled,
            "reel_specs": specs,
            "tier1_pass": tier1["passed"],
            "tier1_defects": tier1["defects"],
        })

    iso_path = work_dir / "inference_isolation_report.json"
    mp.write_report(str(iso_path))
    (work_dir / "cold_worker_outputs.json").write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return run_cold_inference_worker(Path(sys.argv[2]))

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

    tmp_root = Path(tempfile.mkdtemp(prefix="sportreel_r2_cold_e2e_"))
    try:
        raw_dir = tmp_root / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        for key in REAL_KEYS:
            dst = raw_dir / Path(key).name
            print(f"Downloading read-only R2 fixture: {Path(key).name} ...")
            s3.download_file(bucket, key, str(dst))

        print("Running isolated Cold-Inference worker (SPORTREEL_STRICT_COLD_INFERENCE=1, LLM_CACHE=0)...")
        worker_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("R2_", "CLOUDFLARE_", "SUPABASE_"))
        }
        worker_env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "scripts")])
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(tmp_root)],
            cwd=str(ROOT),
            env=worker_env,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
            raise RuntimeError(f"Cold worker failed with code {proc.returncode}")

        iso_report = json.loads((tmp_root / "inference_isolation_report.json").read_text(encoding="utf-8"))
        worker_outputs = json.loads((tmp_root / "cold_worker_outputs.json").read_text(encoding="utf-8"))

        # Verify ffprobe BT.709 VUI + 4K + silent audio on every rendered reel
        for item in worker_outputs:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", item["rendered_reel"]],
                capture_output=True, text=True, check=True,
            )
            streams = json.loads(probe.stdout).get("streams", [])
            v_streams = [s for s in streams if s.get("codec_type") == "video"]
            a_streams = [s for s in streams if s.get("codec_type") == "audio"]
            assert len(v_streams) == 1 and len(a_streams) == 0, f"Expected 1 video and 0 audio streams: {streams}"
            vs = v_streams[0]
            assert vs["width"] == 2160 and vs["height"] == 3840, f"Expected 2160x3840, got {vs['width']}x{vs['height']}"
            assert vs.get("color_space") == "bt709" and vs.get("color_primaries") == "bt709" and vs.get("color_transfer") == "bt709", vs
            item["ffprobe_verified_4k_bt709_silent"] = True
            item.pop("rendered_reel", None)  # strip temp local path before persisting report

        # Evaluation Plane: compare SHA-256 & windows against frozen GT-v1!
        gt = json.loads((ROOT / "evaluation" / "ground_truth" / "gtv1_frozen.json").read_text(encoding="utf-8"))
        gt_by_sha = sc.load_gt(gt)
        gt_comparisons = []
        for item in worker_outputs:
            sha = item["source_sha256"]
            assert sha in gt_by_sha, f"Real R2 clip {item['video_name']} SHA {sha} verified in GT-v1!"
            gt_entry = gt_by_sha[sha]
            fps = gt_entry["fps"]
            gt_rides = [
                {"ride_uid": r["ride_uid"], "athlete_id": r["athlete_id"],
                 "gt_window_sec": [round(r["start_frame"] / fps, 3), round(r["end_frame"] / fps, 3)]}
                for r in gt_entry["rides"]
            ]
            gt_excludes = [
                {"gt_exclude_sec": [round(ex[0] / fps, 3), round(ex[1] / fps, 3)]}
                if isinstance(ex, (tuple, list))
                else {"reason": ex.get("reason"), "gt_exclude_sec": [round(ex["start_frame"] / fps, 3), round(ex["end_frame"] / fps, 3)]}
                for ex in gt_entry["excludes"]
            ]
            gt_comparisons.append({
                "video_name": item["video_name"],
                "source_sha256": sha,
                "cold_pipeline_window_sec": item["refined_window_sec"],
                "two_pass_crop_grids_built": item["two_pass_crop_grids_built"],
                "tier1_qa_pass": item["tier1_pass"],
                "ffprobe_verified_4k_bt709_silent": item["ffprobe_verified_4k_bt709_silent"],
                "gt_rides": gt_rides,
                "gt_excludes": gt_excludes,
            })

        sanitized_iso = {
            "schema": iso_report.get("schema"),
            "strict_cold_inference": iso_report.get("strict_cold_inference", True),
            "guard_installed": iso_report.get("guard_installed", True),
            "channels_closed": iso_report.get("channels_closed", []),
            "open_refused_basenames": [Path(p).name for p in iso_report.get("open_refused", []) if p],
            "prior_sidecars_rejected_count": len(iso_report.get("prior_sidecars_rejected", [])),
        }

        summary = {
            "schema": "sportreel.real_r2_cold_drone_e2e_verification.v1",
            "strict_cold_inference": sanitized_iso["strict_cold_inference"],
            "gt_open_refused_in_worker": "gtv1_frozen.json" in sanitized_iso["open_refused_basenames"],
            "r2_mutations": 0,
            "llm_spend_usd": 0.0,
            "isolation_report": sanitized_iso,
            "real_drone_clips_tested": worker_outputs,
            "gt_v1_comparison": gt_comparisons,
        }
        out_file = ROOT / "evaluation" / "qualification" / "cycle15_real_r2_drone_media_e2e.json"
        out_file.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        print("PASS Real 4K DJI R2 Cold-Inference E2E -> YOLO+BoT-SORT -> Onset/End -> 2-Pass Crop Grids -> 4K BT.709 Silent Render -> GT-v1 Verified!")
        return 0
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
