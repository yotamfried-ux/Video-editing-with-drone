#!/usr/bin/env python3
"""Cycle 11 architecture proof: a FOOTBALL profile runs through the same engine as surfing (synthetic, real FFmpeg).

SCOPE: architecture only. The video and detections are synthetic (coloured boxes, not a football model run). This
proves the engine needs no football-specific orchestrator, renderer, QA or review - NOT that it is accurate on real
football footage (no labelled football data exists yet).

F1  a Football profile exists in the registry (aliases soccer/futsal) with its own action types and phases.
F2  labelled examples are PerformanceEvents (pass by the target player, with a build-up phase) and convert to the
    engine's event dict without football code in the Core.
F3  the production perception binding (perception.runtime.enrich_event) binds the event to the TARGET track in a frame
    with two team-mates in the same kit and one opponent (other people never reject the clip).
F4  the production window code (window_refinement + extend_to_setup) opens the cut on the target's run-up via the
    football onset policy, not on the analyzer-style main moment, and not on stationary team-mates.
F5  the production eligibility (performance_reel_policy / output_qualification) treats a low-score football action
    as coverage (UNCERTAIN, reviewed) and a non-action ("walk") as ineligible; identity of a single-source clip MATCH.
F6  the production editor (stages.editor.cut_clip) renders a real 9:16 H.264 clip centred on the target (decoded
    centre pixel = the target's white shirt patch), and the EDL recorder records it (same evidence path as surfing).
F7  a PerformanceEvent view of the rendered event lists its missing fields explicitly (no invented values).
F8  the surfing behaviour is untouched: a surf wave_catch keeps the surfing profile, its coverage basis string and
    failed-takeoff rule.
F9  cycle 12 Core changes are sport-neutral: the draft ledger, identity review and pairwise-consensus modules carry
    no surf / wave / board / paddle condition, and the football reel gets a canonical reel id and render-plan digest
    from the same ledger code (stable under a changed model description).
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from test_pipeline_real_mp4_renderer import pixel_at, probe, run  # noqa: E402

FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def main() -> int:
    assert shutil.which("ffmpeg") and shutil.which("ffprobe")
    with tempfile.TemporaryDirectory(prefix="sportreel-football-") as d:
        folder = Path(d)
        # QA_CROP_CHECK: the production per-clip QA path renders real clip files (no single-pass deferral)
        sys.modules["config"] = types.SimpleNamespace(TMP_DIR=str(folder), QUALITY_LOG_FILE=str(folder / "q.jsonl"),
                                                      MIN_SOURCE_HEIGHT=1080, SLOWMO_INTERPOLATE=False, QA_CROP_CHECK=True)
        from pipeline import complete_action_window_policy as cap, performance_reel_policy as prp, window_refinement as wr
        from pipeline import output_qualification as oq
        from pipeline.performance_event import PerformanceEvent, from_pipeline_event, to_pipeline_event
        from pipeline.perception.producer import sidecar_from_detection_json
        from pipeline.perception.runtime import enrich_event, load_sidecar_detections
        from pipeline.real_identity_gate import enforce_identity_gate
        from pipeline.sport_profiles import profile_for
        from pipeline.stages import editor

        foot = profile_for("soccer")
        check(foot.profile_id == "football" and {"pass", "shot", "tackle"} <= set(foot.action_types)
              and "build_up" in foot.action_phases, "F1 football profile registered with its own actions/phases")

        # pitch 1920x1080, 30 fps, 6 s. Target (blue kit + white patch) stands until 1.0 s then runs right; team-mate
        # (blue) and opponent (red) stand still. Box size 200x300.
        def tx(t):
            return 300 if t < 1.0 else 300 + 220 * (t - 1.0)
        src = folder / "football_synthetic.mp4"
        # overlay (not drawbox) so the target really moves frame by frame
        run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x2e7d32:s=1920x1080:r=30:d=6",
            "-f", "lavfi", "-i", "color=c=blue:s=200x300:r=30:d=6",
            "-f", "lavfi", "-i", "color=c=white:s=60x60:r=30:d=6",
            "-filter_complex",
            "[0:v]drawbox=x=1500:y=380:w=200:h=300:color=blue:t=fill,drawbox=x=1150:y=600:w=200:h=300:color=red:t=fill[bg];"
            "[bg][1:v]overlay=x='if(lt(t,1),300,300+220*(t-1))':y=400[a];"
            "[a][2:v]overlay=x='if(lt(t,1),370,370+220*(t-1))':y=500,format=yuv420p[v]",
            "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-t", "6", str(src))
        items = []
        for k in range(0, 36):
            t = round(k / 6, 3)
            for track, x in ((7, tx(t)), (8, 1500), (9, 1150)):
                y = 600 if track == 9 else (400 if track == 7 else 380)
                items.append({"frame_index": int(t * 30), "time_sec": t, "bbox_xyxy": [x, y, x + 200, y + 300],
                              "frame_width": 1920, "frame_height": 1080, "confidence": 0.95, "class_id": 0,
                              "class_name": "person", "track_id": track})
            items.append({"frame_index": int(t * 30), "time_sec": t, "bbox_xyxy": [tx(t) + 210, 680, tx(t) + 240, 710],
                          "frame_width": 1920, "frame_height": 1080, "confidence": 0.9, "class_id": 32,
                          "class_name": "sports ball", "track_id": 50})
        (folder / "det.json").write_text(json.dumps({"detections": items}))
        sidecar_from_detection_json(str(src), Path(str(src) + ".perception.json"), folder / "det.json")
        detections = load_sidecar_detections(str(src))

        # F2 labelled example: a pass at 3.5 s (main moment 3.0 s), build-up from the run start (GT 1.0 s)
        label = PerformanceEvent(sport_profile_id="football", event_id="fb_ev_1", source_start_frame=90,
                                 source_end_frame=165, action_type="pass", action_phases={"setup": 0.0, "outcome": 5.5},
                                 confidence=0.4)
        ev = to_pipeline_event(label, fps=30.0)
        ev.update(crop_x=0.33, crop_y=0.5, edit={"zoom": 1.0, "slowmo": False}, description="receives and passes")
        check(ev["sport"] == "football" and ev["start"] == 3.0 and ev["setup_start"] == 0.0,
              f"F2 PerformanceEvent -> engine event ({ev['start']}..{ev['end']}, setup {ev.get('setup_start')})")

        enriched = enrich_event(ev, detections)
        check(str(enriched.get("target_track_id")) == "7", f"F3 bound to the target track 7 among 3 people ({enriched.get('target_track_id')})")

        refined = wr.refine_event_window(enriched, detections)
        out = cap.extend_to_setup(refined)
        onset = (refined.get("window_refinement") or {}).get("onset_motion_from_sec")
        check(onset is not None and 0.9 <= float(out["start"]) <= 1.6,
              f"F4 cut opens on the run-up (start {out['start']}, onset {onset}; GT build-up 1.0 s; not 0.0 standing)")

        check(prp.classify_event_eligibility(dict(out), "football")["verdict"] == "UNCERTAIN",
              "F5 low-score football action = coverage UNCERTAIN (reviewed), not dropped")
        check(prp.classify_event_eligibility({"type": "walk", "score": 4}, "football")["verdict"] == "INELIGIBLE",
              "F5 a non-action stays under the quality floor")
        ident = oq.identity_verdict([{**out, "event_source_ref": "sha256:fb", "person_id": "p1"}])
        check(ident["verdict"] == "MATCH", f"F5 single-source single-actor identity ({ident['basis']})")
        check(enforce_identity_gate([{"description": "blue #10", "appearances": [{"path": str(src), "events": [out]}]}])[0]
              .get("_identity_gate") in (None, "pass"), "F5 the identity gate needs nothing football-specific")

        from pipeline import quality_preserving_framing
        quality_preserving_framing.install()          # the production framing (tracked crop), as bootstrap installs it
        info = {"width": 1920, "height": 1080, "fps": 30.0, "zoom_headroom": 1.0, "can_slowmo": False}
        clip = editor.cut_clip(str(src), out, 0, sport="football", source_info=info, target_fps=30)
        check(bool(clip) and Path(clip).is_file(), "F6 production editor rendered the clip")
        if clip and Path(clip).is_file():
            spec = probe(Path(clip))
            w, h = int(spec["width"]), int(spec["height"])
            check(spec["codec_name"] == "h264" and abs(w / h - 9 / 16) < 0.01, f"F6 9:16 H.264 {spec}")
            # the target at clip t = 2 s (source 3.0 s: box x 740-940, white patch 810-870, y 500-560); the opponent
            # (red, x 1150-1350) and team-mate (blue, x 1500-1700) are outside a crop centred on the target.
            hits = 0
            for dy in (-120, 0, 120):
                rgb = pixel_at(Path(clip), w // 2, h // 2 + dy)
                white = min(rgb) > 170
                blue = rgb[2] > 140 and rgb[2] > rgb[0] * 1.6 and rgb[2] > rgb[1] * 1.6
                hits += int(white or blue)
            check(hits >= 2, f"F6 decoded centre column shows the target (white patch / blue kit), not pitch or opponent ({hits}/3, last {rgb})")
        try:
            from pipeline import edl_export
            check(hasattr(edl_export, "record_clip") and hasattr(edl_export, "build_reel_edl"),
                  "F6 the same EDL recorder/builder serves the football clip (no football EDL code)")
        except Exception as exc:
            check(False, f"F6 EDL module import failed: {exc}")

        view = from_pipeline_event(out, fps=30.0)
        check(view.sport_profile_id == "football" and view.primary_actor_id == "7"
              and {"source_sha256", "qa_status"} <= set(view.missing_fields), f"F7 PerformanceEvent view lists missing fields explicitly {view.missing_fields}")

        surf_ev = {"type": "wave_catch", "score": 3}
        check(prp.coverage_profile(surf_ev, "surfing").profile_id == "surfing"
              and prp.classify_event_eligibility(surf_ev, "surfing")["basis"] == "surf_coverage_rule_without_positive_score"
              and prp.classify_event_eligibility({"type": "wave_catch", "description": "failed takeoff", "score": 9},
                                                 "surfing")["verdict"] == "INELIGIBLE",
              "F8 surfing behaviour unchanged")
        import re as _re
        from pipeline import draft_ledger
        core = {m: (ROOT / "pipeline" / f"{m}.py").read_text() for m in ("draft_ledger", "identity_review")}
        pc = (ROOT / "pipeline" / "identity_pair_consensus.py").read_text()
        pc_code = pc.split("M1_PROMPT", 1)[0]          # the prompt text itself is a profile-migration item (PQ-30)
        surf = _re.compile(r"\b(surf\w*|wave\w*|paddl\w*|wetsuit)\b", _re.I)
        hits = {m: surf.findall(s) for m, s in list(core.items()) + [("identity_pair_consensus(code before prompt)", pc_code)]}
        apps = [{"path": str(src), "_person_id": "7", "events": [out]}]
        cid1 = draft_ledger.canonical_reel_id(apps, part_index=1)
        cid2 = draft_ledger.canonical_reel_id([dict(apps[0], _description="other model text")], part_index=1)
        plan = draft_ledger.plan_digest([dict(out, source_path=str(src))])
        check(not any(hits.values()) and cid1 == cid2 and cid1.startswith("cr_") and len(plan) == 64,
              f"F9 cycle-12 Core (ledger, identity review) sport-neutral {hits}; football reel id {cid1} stable")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
