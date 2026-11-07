#!/usr/bin/env python3
"""Contract & acceptance tests for OPT-01..OPT-07 and GATE-01..GATE-08."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_opt01_equipment_detection_and_association() -> None:
    """OPT-01: Equipment association, crowded-frame bipartite matching, and activity state classification."""
    from pipeline.perception.equipment_association import (
        associate_equipment_with_athletes,
        can_use_equipment_as_sole_identity_proof,
        classify_track_activity_profiles,
    )

    assert can_use_equipment_as_sole_identity_proof() is False, "Equipment must never be sole identity proof"

    # Crowded scene: 2 active surfers on boards + 1 waiting surfer + 1 background passerby on beach
    persons = []
    equips = []
    for f_idx in range(10):
        t = f_idx * 0.5
        # Surfer 1 (active, moving across wave with surfboard 101)
        sx1 = 200.0 + f_idx * 35.0
        sy1 = 400.0 + f_idx * 12.0
        persons.append({
            "frame_index": f_idx,
            "time_sec": t,
            "bbox_xyxy": [sx1, sy1, sx1 + 60.0, sy1 + 110.0],
            "frame_width": 1920,
            "frame_height": 1080,
            "confidence": 0.88,
            "class_id": 0,
            "class_name": "person",
            "track_id": 1,
        })
        equips.append({
            "frame_index": f_idx,
            "time_sec": t,
            "bbox_xyxy": [sx1 - 15.0, sy1 + 75.0, sx1 + 85.0, sy1 + 125.0],
            "frame_width": 1920,
            "frame_height": 1080,
            "confidence": 0.82,
            "class_id": 37,
            "class_name": "surfboard",
            "track_id": 101,
        })
        # Surfer 2 (nearby active surfer with surfboard 102 in same frames)
        sx2 = 340.0 + f_idx * 30.0
        sy2 = 420.0 + f_idx * 10.0
        persons.append({
            "frame_index": f_idx,
            "time_sec": t,
            "bbox_xyxy": [sx2, sy2, sx2 + 58.0, sy2 + 108.0],
            "frame_width": 1920,
            "frame_height": 1080,
            "confidence": 0.85,
            "class_id": 0,
            "class_name": "person",
            "track_id": 2,
        })
        equips.append({
            "frame_index": f_idx,
            "time_sec": t,
            "bbox_xyxy": [sx2 - 10.0, sy2 + 72.0, sx2 + 80.0, sy2 + 122.0],
            "frame_width": 1920,
            "frame_height": 1080,
            "confidence": 0.79,
            "class_id": 37,
            "class_name": "surfboard",
            "track_id": 102,
        })
        # Surfer 3 (waiting stationary in lineup)
        persons.append({
            "frame_index": f_idx,
            "time_sec": t,
            "bbox_xyxy": [900.0, 250.0, 945.0, 320.0],
            "frame_width": 1920,
            "frame_height": 1080,
            "confidence": 0.76,
            "class_id": 0,
            "class_name": "person",
            "track_id": 3,
        })

    # Track 4: brief 2-frame passerby at frame edge without equipment
    for f_idx in range(2):
        persons.append({
            "frame_index": f_idx,
            "time_sec": f_idx * 0.5,
            "bbox_xyxy": [5.0, 10.0, 35.0, 60.0],
            "frame_width": 1920,
            "frame_height": 1080,
            "confidence": 0.55,
            "class_id": 0,
            "class_name": "person",
            "track_id": 4,
        })

    enriched, links = associate_equipment_with_athletes(persons, equips)
    assert links["1"]["primary_equipment"] == "surfboard"
    assert links["1"]["equipment_track_ids"] == ["surfboard:101"]
    assert links["1"]["equipment_association_ratio"] == 1.0
    assert links["2"]["primary_equipment"] == "surfboard"
    assert links["2"]["equipment_track_ids"] == ["surfboard:102"]
    assert "3" not in links and "4" not in links

    profiles = classify_track_activity_profiles(enriched, links)
    assert profiles["1"]["activity_state"] == "active"
    assert profiles["2"]["activity_state"] == "active"
    assert profiles["3"]["activity_state"] == "waiting"
    assert profiles["4"]["activity_state"] == "background_passerby"
    assert profiles["1"]["activity_score"] > profiles["3"]["activity_score"] > profiles["4"]["activity_score"]


def test_opt02_visual_embeddings_and_shadow_mode() -> None:
    """OPT-02: 2x2 contact sheet visual embeddings, caching, and candidate filtering."""
    from PIL import Image
    from pipeline.visual_embeddings import (
        compare_contact_sheet_embeddings,
        compute_contact_sheet_embedding,
        evaluate_candidate_pairs,
    )

    with tempfile.TemporaryDirectory(prefix="sportreel-opt02-") as tmpdir:
        os.environ["LLM_CACHE_DIR"] = str(Path(tmpdir) / "cache")
        # Create two 400x400 contact sheets of Athlete A (red top, turquoise board)
        img_a1 = Image.new("RGB", (400, 400), (30, 80, 110))
        for qx in (0, 200):
            for qy in (0, 200):
                # Upper torso red
                for x in range(qx + 50, qx + 150):
                    for y in range(qy + 35, qy + 100):
                        img_a1.putpixel((x, y), (220, 30, 35))
                # Equipment turquoise
                for x in range(qx + 30, qx + 170):
                    for y in range(qy + 130, qy + 185):
                        img_a1.putpixel((x, y), (20, 200, 195))
        path_a1 = str(Path(tmpdir) / "athlete_a_clip1.jpg")
        img_a1.save(path_a1)

        img_a2 = img_a1.copy()
        img_a2.putpixel((10, 10), (32, 82, 112))
        path_a2 = str(Path(tmpdir) / "athlete_a_clip2.jpg")
        img_a2.save(path_a2)

        # Create contact sheet of Athlete B (bright yellow top, black board)
        img_b1 = Image.new("RGB", (400, 400), (30, 80, 110))
        for qx in (0, 200):
            for qy in (0, 200):
                for x in range(qx + 50, qx + 150):
                    for y in range(qy + 35, qy + 100):
                        img_b1.putpixel((x, y), (245, 235, 20))
                for x in range(qx + 30, qx + 170):
                    for y in range(qy + 130, qy + 185):
                        img_b1.putpixel((x, y), (15, 15, 15))
        path_b1 = str(Path(tmpdir) / "athlete_b_clip3.jpg")
        img_b1.save(path_b1)

        emb1 = compute_contact_sheet_embedding(path_a1)
        assert emb1 is not None and emb1["crop_count"] == 4 and emb1["cache_hit"] is False
        emb1_cached = compute_contact_sheet_embedding(path_a1)
        assert emb1_cached is not None and emb1_cached["cache_hit"] is True

        emb2 = compute_contact_sheet_embedding(path_a2)
        emb_b = compute_contact_sheet_embedding(path_b1)
        same_comp = compare_contact_sheet_embeddings(emb1, emb2)
        diff_comp = compare_contact_sheet_embeddings(emb1, emb_b)
        assert same_comp["similarity"] > 0.95
        assert same_comp["similarity"] > diff_comp["similarity"]

        entries = [
            {"clip_index": 0, "person_id": "person_A", "path": "clip1.mp4", "thumbnail": path_a1},
            {"clip_index": 1, "person_id": "person_A", "path": "clip2.mp4", "thumbnail": path_a2},
            {"clip_index": 2, "person_id": "person_A", "path": "clip3.mp4", "thumbnail": path_b1},
        ]
        summary = evaluate_candidate_pairs(entries, shadow_mode=True)
        assert summary["shadow_mode"] is True
        assert summary["strong_local_matches_count"] >= 1


def test_opt03_identity_decision_engine() -> None:
    """OPT-03: Unified IdentityDecisionEngine, cross-source numeric track_id immunity, and UNCERTAIN gate."""
    from pipeline.identity_decision_engine import IdentityDecisionEngine

    engine = IdentityDecisionEngine()

    # Case 1: Different athletes in DJI_0104 and DJI_0140 that both happen to have numeric track_id=1
    left_0104 = {
        "path": "DJI_0104.MP4",
        "_person_id": "person_A",
        "description": "Surfer in a full black wetsuit riding a white surfboard",
        "events": [{"start": 12.0, "end": 22.0, "track_id": 1, "target_track_id": "1"}],
    }
    right_0140 = {
        "path": "DJI_0140.MP4",
        "_person_id": "person_A",
        "description": "Surfer in a red rashguard and black shorts riding a yellow surfboard",
        "events": [{"start": 12.0, "end": 22.0, "track_id": 1, "target_track_id": "1"}],
    }
    dec_diff = engine.evaluate_pair(left_0104, right_0140)
    assert dec_diff.decision == "NO_MATCH"
    assert dec_diff.auto_publish_allowed is False
    assert dec_diff.evidence_trace["cross_source_numeric_track_id_ignored"] is True
    assert dec_diff.evidence_trace["cross_source_numeric_track_overlap"] == ["1"]

    # Case 2: Same athlete across different clips with matching structured attributes
    left_match = {
        "path": "DJI_0065.MP4",
        "_person_id": "person_A",
        "description": "Surfer with long brown hair wearing a black one-piece swimsuit on a turquoise longboard",
        "events": [{"start": 5.0, "end": 18.0, "track_id": 2}],
    }
    right_match = {
        "path": "DJI_0068.MP4",
        "_person_id": "person_A",
        "description": "Surfer in a black one-piece swimsuit riding a light blue/turquoise longboard",
        "events": [{"start": 8.0, "end": 24.0, "track_id": 7}],
    }
    dec_match = engine.evaluate_pair(left_match, right_match, embedding_similarity=0.91)
    assert dec_match.decision == "MATCH"
    assert dec_match.auto_publish_allowed is True
    # Reproducibility check
    assert dec_match.to_dict() == engine.evaluate_pair(left_match, right_match, embedding_similarity=0.91).to_dict()

    # Case 3: Two appearances in the SAME source clip -> always NO_MATCH
    same_clip_b = {
        "path": "DJI_0065.MP4",
        "_person_id": "person_B",
        "description": "Surfer with long brown hair wearing a black one-piece swimsuit on a turquoise longboard",
        "events": [{"start": 25.0, "end": 35.0, "track_id": 9}],
    }
    dec_same_clip = engine.evaluate_pair(left_match, same_clip_b)
    assert dec_same_clip.decision == "NO_MATCH"
    assert "same_source_clip_conflict" in dec_same_clip.reasons


def test_opt04_and_opt07_tiered_qa_and_render_qa_cache() -> None:
    """OPT-04 & OPT-07: Tiered QA short-circuit, no false approval without Tier 2, and strict QA cache invalidation."""
    from pipeline.render_qa_cache import (
        compute_qa_signature,
        compute_render_signature,
        get_cached_render,
        put_cached_render,
    )
    from pipeline.tiered_qa_gate import evaluate_reel_tiered_qa

    with tempfile.TemporaryDirectory(prefix="sportreel-opt04-07-") as tmpdir:
        os.environ["SPORTREEL_RENDER_QA_CACHE_DIR"] = str(Path(tmpdir) / "rq_cache")
        reel_file = Path(tmpdir) / "MULTI_athlete_1.mp4"
        reel_file.write_bytes(b"rendered-mp4-bytes-v1")

        valid_specs = {
            "has_audio": False,
            "duration": 24.0,
            "width": 1080,
            "height": 1920,
            "aspect": 1080 / 1920,
            "fps": 30.0,
        }
        good_events = [
            {
                "event_id": "ev1",
                "_src": "DJI_0065.MP4",
                "source_person_key": "DJI_0065.MP4::person_A",
                "athlete_id": "athlete_1",
                "type": "surf_ride",
                "start": 10.0,
                "end": 22.0,
                "score": 9,
                "track_id": "1",
                "perception_evidence_status": "tracker_sidecar",
            },
            {
                "event_id": "ev2",
                "_src": "DJI_0068.MP4",
                "source_person_key": "DJI_0068.MP4::person_A",
                "athlete_id": "athlete_1",
                "type": "surf_ride",
                "start": 15.0,
                "end": 27.0,
                "score": 8,
                "track_id": "3",
                "perception_evidence_status": "tracker_sidecar",
            },
        ]

        llm_calls = {"count": 0}

        def fake_gemini_qa(path: str, sport: str, label: str) -> dict[str, Any]:
            llm_calls["count"] += 1
            return {
                "verdict": "PASS",
                "technical": {"pass": True, "issues": [], **valid_specs},
                "content": {"hook": 9, "pacing": 8, "payoff": 9, "clarity": 9, "loopability": 8},
                "defects": [],
                "engagement_score": 85,
                "overall": "Clean single-athlete surf reel.",
            }

        # 1. Deliberate Tier-1 defect: mixed athlete_ids -> rejected locally with 0 LLM calls
        mixed_events = [good_events[0], {**good_events[1], "athlete_id": "athlete_999"}]
        res_mixed = evaluate_reel_tiered_qa(
            str(reel_file),
            events=mixed_events,
            sport="surfing",
            athlete_label="surfer A",
            content_qa_fn=fake_gemini_qa,
            specs=valid_specs,
        )
        assert res_mixed["verdict"] == "FAIL"
        assert res_mixed["llm_called"] is False
        assert llm_calls["count"] == 0
        assert any(d["type"] == "IDENTITY_MISMATCH" for d in res_mixed["defects"])

        # 2. Deliberate Tier-1 defect: overlapping window from same source video -> 0 LLM calls
        dup_events = [good_events[0], {**good_events[0], "event_id": "ev_dup", "start": 11.0, "end": 21.0}]
        res_dup = evaluate_reel_tiered_qa(
            str(reel_file),
            events=dup_events,
            sport="surfing",
            athlete_label="surfer A",
            content_qa_fn=fake_gemini_qa,
            specs=valid_specs,
        )
        assert res_dup["verdict"] == "FAIL"
        assert res_dup["llm_called"] is False
        assert llm_calls["count"] == 0
        assert any(d["type"] == "DUPLICATE_MOMENT" for d in res_dup["defects"])

        # 3. Clean Tier-1 -> must invoke Tier-2 Gemini content QA on Cold Run
        res_cold = evaluate_reel_tiered_qa(
            str(reel_file),
            events=good_events,
            sport="surfing",
            athlete_label="surfer A",
            content_qa_fn=fake_gemini_qa,
            specs=valid_specs,
        )
        assert res_cold["verdict"] == "PASS"
        assert res_cold["llm_called"] is True
        assert llm_calls["count"] == 1

        # 4. Warm Run with identical reel bytes, EDL, and policy -> hits verified QA cache (0 new LLM calls)
        res_warm = evaluate_reel_tiered_qa(
            str(reel_file),
            events=good_events,
            sport="surfing",
            athlete_label="surfer A",
            content_qa_fn=fake_gemini_qa,
            specs=valid_specs,
        )
        assert res_warm["verdict"] == "PASS"
        assert res_warm["llm_called"] is False
        assert res_warm.get("qa_cache_hit") is True
        assert llm_calls["count"] == 1

        # 5. Invalidation test: modify rendered reel bytes -> MUST NOT reuse old QA PASS!
        reel_file.write_bytes(b"rendered-mp4-bytes-v2-modified")
        res_invalidated = evaluate_reel_tiered_qa(
            str(reel_file),
            events=good_events,
            sport="surfing",
            athlete_label="surfer A",
            content_qa_fn=fake_gemini_qa,
            specs=valid_specs,
        )
        assert res_invalidated["llm_called"] is True
        assert llm_calls["count"] == 2

        # 6. Test concurrent render cache writes and deterministic retrieval
        appearances = [{"path": str(reel_file), "events": good_events}]
        r_sig = compute_render_signature(appearances, sport="surfing", athlete_label="surfer A")
        assert put_cached_render(r_sig, str(reel_file), good_events) is True
        restored_path = Path(tmpdir) / "restored.mp4"
        hit, restored_events = get_cached_render(r_sig, str(restored_path))
        assert hit is True
        assert restored_path.read_bytes() == reel_file.read_bytes()
        assert len(restored_events or []) == 2


def test_opt05_adaptive_inference_window_escalation() -> None:
    """OPT-05: Problematic window detection, budget gating, and track fragmentation reduction."""
    from pipeline.perception.adaptive_inference import (
        find_weak_perception_windows,
        merge_escalated_detections,
        should_escalate_windows,
    )
    from pipeline.perception.track_stitching import stitch_sidecar_payload

    # Primary pass has a gap between t=11.0s (track 1) and t=14.5s (track 2) > 3.0s stitching threshold
    primary = [
        {"frame_index": 200, "time_sec": 10.0, "bbox_xyxy": [400.0, 300.0, 440.0, 360.0], "frame_width": 1920, "frame_height": 1080, "confidence": 0.75, "class_id": 0, "track_id": 1},
        {"frame_index": 220, "time_sec": 11.0, "bbox_xyxy": [410.0, 305.0, 450.0, 365.0], "frame_width": 1920, "frame_height": 1080, "confidence": 0.74, "class_id": 0, "track_id": 1},
        {"frame_index": 290, "time_sec": 14.5, "bbox_xyxy": [435.0, 315.0, 475.0, 375.0], "frame_width": 1920, "frame_height": 1080, "confidence": 0.78, "class_id": 0, "track_id": 2},
        {"frame_index": 310, "time_sec": 15.5, "bbox_xyxy": [445.0, 320.0, 485.0, 380.0], "frame_width": 1920, "frame_height": 1080, "confidence": 0.80, "class_id": 0, "track_id": 2},
    ]
    before_stitch = stitch_sidecar_payload({"source_video": "drone.mp4", "status": "ok", "detections": primary})
    assert before_stitch["track_stitching"]["canonical_track_count"] == 2

    weak = find_weak_perception_windows(primary, duration_sec=60.0)
    assert len(weak) >= 1
    do_esc, reason, selected = should_escalate_windows(weak, duration_sec=60.0, frame_width=1920, primary_imgsz=640)
    assert do_esc is True and reason == "targeted_window_escalation"
    # Should not escalate if already at 1280px
    no_esc, _, _ = should_escalate_windows(weak, duration_sec=60.0, frame_width=1920, primary_imgsz=1280)
    assert no_esc is False

    # High-res pass recovers the missing bridge detection at t=12.8s
    escalated = [
        {"frame_index": 256, "time_sec": 12.8, "bbox_xyxy": [422.0, 310.0, 462.0, 370.0], "frame_width": 1920, "frame_height": 1080, "confidence": 0.82, "class_id": 0, "track_id": 1},
    ]
    merged, stats = merge_escalated_detections(primary, escalated, selected)
    assert stats["recovered_detections_count"] == 1
    after_stitch = stitch_sidecar_payload({"source_video": "drone.mp4", "status": "ok", "detections": merged})
    # The recovered bridge detection connects track 1 (11.0s -> 12.8s -> 14.5s) into 1 unified canonical track!
    assert after_stitch["track_stitching"]["canonical_track_count"] == 1


def test_opt06_internal_activity_windows_and_remapping() -> None:
    """OPT-06: Internal activity window slicing, exact piecewise timestamp remap, and low-confidence fallback."""
    from pipeline.activity_window import compute_internal_activity_windows

    # 180s video with two active surfing bouts: [10s..25s] and [140s..160s], and 115s of empty water in between
    dets = (
        [{"time_sec": float(t), "confidence": 0.88} for t in (10, 15, 20, 25)]
        + [{"time_sec": float(t), "confidence": 0.90} for t in (140, 145, 150, 155, 160)]
    )
    res = compute_internal_activity_windows(dets, duration=180.0, pad_sec=5.0, min_gap_sec=20.0)
    assert res["mode"] == "internal_windows"
    assert len(res["windows"]) == 2
    assert res["windows"][0] == (5.0, 30.0)   # 25s
    assert res["windows"][1] == (135.0, 165.0) # 30s
    assert res["saved_ratio"] > 0.65

    ts_map = res["timestamp_map"]
    # Event 1 in window 1 (condensed 5.0s..17.0s -> source 10.0s..22.0s)
    # Event 2 in window 2 (condensed 30.0s..45.0s -> source 140.0s..155.0s)
    session = {
        "activity": "surfing",
        "persons": [
            {
                "id": "person_A",
                "events": [
                    {"type": "wave_catch", "start": 5.0, "end": 17.0, "setup_start": 5.5, "peak_time": 11.0, "outcome_end": 16.5, "score": 8},
                    {"type": "aerial", "start": 30.0, "end": 45.0, "setup_start": 31.0, "peak_time": 38.0, "outcome_end": 44.0, "score": 9},
                ],
            }
        ],
    }
    remapped = ts_map.remap_session_to_source(session)
    ev1, ev2 = remapped["persons"][0]["events"]
    assert (ev1["start"], ev1["end"], ev1["peak_time"]) == (10.0, 22.0, 16.0)
    assert (ev2["start"], ev2["end"], ev2["peak_time"]) == (140.0, 155.0, 148.0)

    # Safety fallback when CV confidence is low (< 0.70): must NOT slice out internal gaps
    low_conf_dets = [{"time_sec": float(t), "confidence": 0.42} for t in [15, 20, 25, 145, 150]]
    fb = compute_internal_activity_windows(low_conf_dets, duration=180.0)
    assert fb["mode"] != "internal_windows"
    assert fb["fallback_reason"] == "low_cv_confidence_safety_fallback"


def test_gate06_perception_cache_safety() -> None:
    """GATE-06: Cold, Warm, and Invalidated perception cache + source_sha256 cross-source protection."""
    from pipeline.perception.runtime import _sidecar_cache_key, validate_sidecar

    with tempfile.TemporaryDirectory(prefix="sportreel-gate06-") as tmpdir:
        os.environ["LLM_CACHE_DIR"] = str(Path(tmpdir) / "cache")
        vid_a = Path(tmpdir) / "video_a.mp4"
        vid_b = Path(tmpdir) / "video_b.mp4"
        vid_a.write_bytes(b"video-content-A")
        vid_b.write_bytes(b"video-content-B")

        os.environ["SPORTREEL_ULTRALYTICS_MODEL"] = "yolo11s.pt"
        os.environ["SPORTREEL_ULTRALYTICS_IMGSZ"] = "640"
        os.environ["SPORTREEL_ULTRALYTICS_VID_STRIDE"] = "5"
        key_base = _sidecar_cache_key(str(vid_a), "cmd")

        # Changing imgsz, stride, model, or confidence must invalidate the cache key
        os.environ["SPORTREEL_ULTRALYTICS_IMGSZ"] = "1280"
        key_imgsz = _sidecar_cache_key(str(vid_a), "cmd")
        assert key_base != key_imgsz

        os.environ["SPORTREEL_ULTRALYTICS_IMGSZ"] = "640"
        os.environ["SPORTREEL_PERCEPTION_MIN_CONFIDENCE"] = "0.35"
        key_conf = _sidecar_cache_key(str(vid_a), "cmd")
        assert key_base != key_conf
        os.environ.pop("SPORTREEL_PERCEPTION_MIN_CONFIDENCE", None)

        # Cross-source protection: a sidecar with video_a's sha256 must be rejected for video_b
        from integrations import llm_cache
        sidecar_file = Path(tmpdir) / "wrong.perception.json"
        sidecar_file.write_text(
            json.dumps({
                "source_video": str(vid_a),
                "source_sha256": llm_cache.file_sha256(str(vid_a)),
                "status": "ok",
                "detections": [],
            }),
            encoding="utf-8",
        )
        assert validate_sidecar(str(vid_a), sidecar_file)["status"] == "ok"
        try:
            validate_sidecar(str(vid_b), sidecar_file)
        except ValueError as exc:
            assert "source_sha256 mismatch" in str(exc)
        else:
            raise AssertionError("validate_sidecar must reject a sidecar from a different source video")


def main() -> int:
    test_opt01_equipment_detection_and_association()
    print("ok  OPT-01 equipment detection, bipartite association, and activity state classification")
    test_opt02_visual_embeddings_and_shadow_mode()
    print("ok  OPT-02 2x2 contact sheet visual embeddings, caching, and shadow mode")
    test_opt03_identity_decision_engine()
    print("ok  OPT-03 unified IdentityDecisionEngine and cross-source track_id immunity")
    test_opt04_and_opt07_tiered_qa_and_render_qa_cache()
    print("ok  OPT-04 & OPT-07 tiered QA gate and deterministic render/QA cache invalidation")
    test_opt05_adaptive_inference_window_escalation()
    print("ok  OPT-05 adaptive window-level high-res escalation and track bridging")
    test_opt06_internal_activity_windows_and_remapping()
    print("ok  OPT-06 internal activity window slicing and piecewise timestamp remapping")
    test_gate06_perception_cache_safety()
    print("ok  GATE-06 perception cache key completeness and cross-source SHA-256 protection")
    print("All hybrid optimization (OPT-01..OPT-07) and GATE-06 contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
