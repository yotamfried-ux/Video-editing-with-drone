#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from integrations import llm_cache as _llm_cache
from pipeline.perception.adaptive_inference import (
    find_weak_perception_windows,
    merge_escalated_detections,
    should_escalate_windows,
)
from pipeline.perception.equipment_association import (
    ALL_DETECTION_CLASS_IDS,
    SPORTS_EQUIPMENT_CLASSES,
    associate_equipment_with_athletes,
    classify_track_activity_profiles,
    is_equipment_class,
)
from pipeline.perception.producer import _tensor_values, detections_from_ultralytics_result, generate_sidecar
from pipeline.perception.track_stitching import stitch_sidecar_payload

_ULTRALYTICS_BACKENDS = {"ultralytics", "yolo", "yolo_track"}
_DEFAULT_TRACKER = "botsort.yaml"
_DEFAULT_VID_STRIDE = 10
_DEFAULT_IMGSZ = 640
_PERSON_CLASSES = [0]


def _positive_int(raw: str | None, default: int, label: str) -> int:
    value = (raw or "").strip()
    if not value:
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return parsed


def _fps(raw: str | None, video_path: str) -> float | None:
    # Prefer true container FPS (24, 29.97, 30, 50, 59.94, 60, etc.) unless explicitly forced
    raw_val = (raw or "").strip().lower()
    env_val = os.getenv("SPORTREEL_ULTRALYTICS_FPS", "auto").strip().lower()
    value = raw_val or env_val

    if value not in {"", "auto", "detect", "native"}:
        try:
            fps = float(value)
            if fps > 0:
                return fps
        except ValueError:
            pass

    try:
        import cv2  # type: ignore
        cap = cv2.VideoCapture(video_path)
        detected = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        cap.release()
        if detected > 0:
            return round(detected, 3)
    except Exception:
        pass
    return 30.0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class _DetectorStats:
    """What the detector saw, independent of whether the tracker confirmed an ID.

    A sidecar with zero tracked detections is rejected by the production policy. These counters tell
    "nothing person-like in any sampled frame" (raw_person_boxes == 0) apart from "persons were detected
    but the tracker never confirmed a track" (raw_person_boxes > 0), which need different fixes.
    """

    def __init__(self) -> None:
        self.frames = 0
        self.raw_boxes = 0
        self.max_confidence: float | None = None
        self.width = 0
        self.height = 0

    def observe(self, result: Any) -> None:
        self.frames += 1
        try:
            shape = getattr(result, "orig_shape", None) or (0, 0)
            self.height, self.width = int(shape[0]), int(shape[1])
            boxes = getattr(result, "boxes", None)
            confidences = [float(value) for value in _tensor_values(getattr(boxes, "conf", None))]
            cls_values = [int(value) for value in _tensor_values(getattr(boxes, "cls", None))]
            person_confs = [
                conf for idx, conf in enumerate(confidences)
                if idx >= len(cls_values) or cls_values[idx] == 0
            ]
            self.raw_boxes += len(person_confs)
            if person_confs:
                best = max(person_confs)
                self.max_confidence = best if self.max_confidence is None else max(self.max_confidence, best)
        except Exception:  # noqa: BLE001 - statistics must never break detection
            pass

    def as_payload(self) -> dict[str, Any]:
        return {
            "frames_processed": self.frames,
            "raw_person_boxes": self.raw_boxes,
            "max_person_confidence": None if self.max_confidence is None else round(self.max_confidence, 3),
            "frame_width": self.width,
            "frame_height": self.height,
        }


def _split_person_and_equipment(all_detections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    persons: list[dict[str, Any]] = []
    equipment: list[dict[str, Any]] = []
    for det in all_detections:
        cid = det.get("class_id")
        cname = det.get("class_name")
        if is_equipment_class(cid, cname):
            if not cname and cid is not None and int(cid) in SPORTS_EQUIPMENT_CLASSES:
                det = {**det, "class_name": SPORTS_EQUIPMENT_CLASSES[int(cid)]}
            equipment.append(det)
        else:
            persons.append(det)
    return persons, equipment


def _run_targeted_window_escalation(
    video_path: str,
    model_name: str,
    tracker: str,
    device: str,
    fps: float,
    weak_windows: list[dict[str, Any]],
    target_classes: list[int],
    escalation_stride: int,
    escalation_imgsz: int = 1280,
) -> tuple[list[dict[str, Any]], int]:
    """Run high-resolution YOLO tracking only on frames inside weak_windows (OPT-05)."""
    if not os.path.exists(video_path) or not weak_windows:
        return [], 0
    try:
        import cv2  # type: ignore
        from ultralytics import YOLO
    except Exception:
        return [], 0

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return [], 0

    escalated: list[dict[str, Any]] = []
    frames_evaluated = 0
    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        model_obj = YOLO(model_name)
        for win in weak_windows:
            start_frame = max(0, int(float(win["start_sec"]) * fps))
            end_frame = int(float(win["end_sec"]) * fps)
            if total_frames > 0:
                end_frame = min(total_frames - 1, end_frame)
            for f_idx in range(start_frame, end_frame + 1, max(1, escalation_stride)):
                cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                frames_evaluated += 1
                track_kwargs: dict[str, Any] = {
                    "source": frame,
                    "tracker": tracker,
                    "persist": True,
                    "verbose": False,
                    "imgsz": escalation_imgsz,
                    "conf": 0.18,
                    "classes": target_classes,
                }
                if device:
                    track_kwargs["device"] = device
                results = model_obj.track(**track_kwargs)
                for res in results or []:
                    escalated.extend(detections_from_ultralytics_result(res, frame_index=f_idx, fps=fps))
    except Exception:
        pass
    finally:
        cap.release()
    return escalated, frames_evaluated


def _fast_ultralytics_sidecar(args: argparse.Namespace) -> dict[str, Any]:
    model = (args.ultralytics_model or os.getenv("SPORTREEL_ULTRALYTICS_MODEL", "")).strip()
    if not model:
        return generate_sidecar(args.video_path, args.output_path, backend="ultralytics")
    tracker = (args.ultralytics_tracker or os.getenv("SPORTREEL_ULTRALYTICS_TRACKER", "")).strip() or _DEFAULT_TRACKER
    stride = _positive_int(args.ultralytics_vid_stride or os.getenv("SPORTREEL_ULTRALYTICS_VID_STRIDE", ""), _DEFAULT_VID_STRIDE, "vid_stride")
    imgsz = _positive_int(args.ultralytics_imgsz or os.getenv("SPORTREEL_ULTRALYTICS_IMGSZ", ""), _DEFAULT_IMGSZ, "imgsz")
    device = (args.ultralytics_device or os.getenv("SPORTREEL_ULTRALYTICS_DEVICE", "")).strip()
    fps = _fps(args.fps, args.video_path)
    detect_equipment = os.getenv("SPORTREEL_DETECT_EQUIPMENT", "1").strip().lower() not in {"0", "false", "no", "off"}
    target_classes = ALL_DETECTION_CLASS_IDS if detect_equipment else [0]

    from ultralytics import YOLO

    def _run_track_pass(current_stride: int, current_imgsz: int, conf_override: float | None = None) -> tuple[list[dict[str, Any]], _DetectorStats]:
        stride = current_stride
        track_kwargs: dict[str, Any] = {
            "source": args.video_path,
            "tracker": tracker,
            "persist": True,
            "stream": True,
            "verbose": False,
            "vid_stride": stride,
            "imgsz": current_imgsz,
            "classes": target_classes,
        }
        if conf_override is not None:
            track_kwargs["conf"] = conf_override
        if device:
            track_kwargs["device"] = device

        model_obj = YOLO(model)
        pass_detections: list[dict[str, Any]] = []
        pass_seen = _DetectorStats()
        for result_index, result in enumerate(model_obj.track(**track_kwargs)):
            pass_seen.observe(result)
            pass_detections.extend(
                detections_from_ultralytics_result(result, frame_index=result_index * stride, fps=fps)
            )
        return pass_detections, pass_seen

    t0_primary = time.monotonic()
    raw_all, seen = _run_track_pass(stride, imgsz)
    cpu_sec_primary = round(time.monotonic() - t0_primary, 3)
    person_detections, equipment_detections = _split_person_and_equipment(raw_all)

    # Whole-video high-res fallback when 0 person detections were found at 640px
    if not person_detections and imgsz < 1280:
        fallback_imgsz = 1280
        fallback_stride = max(1, min(stride, 5))
        fb_all, fb_seen = _run_track_pass(fallback_stride, fallback_imgsz, conf_override=0.15)
        fb_persons, fb_equip = _split_person_and_equipment(fb_all)
        if fb_persons:
            person_detections = fb_persons
            equipment_detections = fb_equip
            seen = fb_seen
            imgsz = fallback_imgsz
            stride = fallback_stride

    # OPT-05: Targeted window-level adaptive high-res inference when primary pass has weak/fragmented windows
    duration_sec = (seen.frames * stride / (fps or 30.0)) if seen.frames > 0 else 0.0
    weak_windows = find_weak_perception_windows(person_detections, duration_sec=duration_sec)
    do_escalate, esc_reason, selected_windows = should_escalate_windows(
        weak_windows,
        duration_sec=duration_sec,
        frame_width=seen.width,
        primary_imgsz=imgsz,
    )
    adaptive_meta: dict[str, Any] = {
        "enabled": True,
        "escalated": False,
        "reason": esc_reason,
        "weak_windows_count": len(weak_windows),
        "selected_windows_count": len(selected_windows),
        "escalated_frames_count": 0,
        "recovered_detections_count": 0,
        "upgraded_detections_count": 0,
        "cpu_seconds_primary": cpu_sec_primary,
        "cpu_seconds_escalation": 0.0,
    }
    if do_escalate and selected_windows and os.path.exists(args.video_path):
        t0_esc = time.monotonic()
        esc_all, esc_frames = _run_targeted_window_escalation(
            args.video_path,
            model_name=model,
            tracker=tracker,
            device=device,
            fps=fps or 30.0,
            weak_windows=selected_windows,
            target_classes=target_classes,
            escalation_stride=max(1, stride // 2),
            escalation_imgsz=1280,
        )
        cpu_sec_esc = round(time.monotonic() - t0_esc, 3)
        esc_persons, esc_equips = _split_person_and_equipment(esc_all)
        person_detections, merge_stats = merge_escalated_detections(person_detections, esc_persons, selected_windows)
        if esc_equips:
            equipment_detections, _ = merge_escalated_detections(equipment_detections, esc_equips, selected_windows)
        adaptive_meta.update({
            **merge_stats,
            "escalated_frames_count": esc_frames,
            "cpu_seconds_escalation": cpu_sec_esc,
        })

    classification = "normal"
    empty_scene_verified = False
    if not person_detections and os.path.exists(args.video_path):
        import cv2
        cap = cv2.VideoCapture(args.video_path)
        can_read = False
        frame_cnt = 0
        if cap.isOpened():
            can_read, _ = cap.read()
            frame_cnt = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            cap.release()

        if not can_read or frame_cnt <= 0:
            payload = {
                "source_video": args.video_path,
                "status": "failed",
                "reason": "corrupt_video_cannot_read_frames",
                "technical_failure": True,
                "detections": [],
                "raw_person_boxes": 0,
            }
            _write_json(Path(args.output_path), payload)
            return payload

        # Zero-detection rescue: dense escalation scan at 1280px with lower stride
        dense_stride = max(1, stride // 3)
        esc_all, esc_frames = _run_targeted_window_escalation(
            args.video_path,
            model_name=model,
            tracker=tracker,
            device=device,
            fps=fps or 30.0,
            weak_windows=[{"start_sec": 0.0, "end_sec": frame_cnt / (fps or 30.0)}],
            target_classes=target_classes,
            escalation_stride=dense_stride,
            escalation_imgsz=1280,
        )
        esc_persons, esc_equips = _split_person_and_equipment(esc_all)
        if esc_persons:
            person_detections = esc_persons
            equipment_detections = esc_equips
            adaptive_meta.update({
                "zero_detection_rescue": True,
                "rescued_detections_count": len(person_detections),
                "escalated_frames_count": esc_frames,
            })
        else:
            # A detector miss is NOT independent evidence that a readable scene
            # contains no athlete. Keep this source reviewable and do not silently
            # discard possible surfers (especially tiny/distant/occluded people).
            empty_scene_verified = False
            classification = "review_required"
            adaptive_meta.update({
                "zero_detection_unresolved": True,
                "zero_detection_escalated_frames": esc_frames,
            })

    source_sha = _llm_cache.file_sha256(args.video_path) if os.path.exists(args.video_path) else None
    payload: dict[str, Any] = {
        "source_video": args.video_path,
        "source_sha256": source_sha,
        "status": "ok",
        "classification": classification,
        "empty_scene_verified": empty_scene_verified,
        "review_required": classification == "review_required",
        "reason": ("zero_person_detections_unverified" if classification == "review_required" else None),
        "backend": "ultralytics",
        "model": model,
        "tracker": tracker,
        "vid_stride": stride,
        "imgsz": imgsz,
        "classes": target_classes,
        **seen.as_payload(),
        "detections": person_detections,
        "equipment_detections": equipment_detections,
        "adaptive_inference": adaptive_meta,
    }
    payload = stitch_sidecar_payload(payload, source_video=args.video_path)
    if equipment_detections:
        eq_sidecar = stitch_sidecar_payload(
            {"source_video": args.video_path, "status": "ok", "detections": equipment_detections},
            source_video=args.video_path,
        )
        payload["equipment_detections"] = eq_sidecar.get("detections", [])

    # OPT-01: Associate sports equipment with stitched athlete tracks and classify activity states
    enriched_persons, equip_links = associate_equipment_with_athletes(
        payload.get("detections", []),
        payload.get("equipment_detections", []),
    )
    activity_profiles = classify_track_activity_profiles(enriched_persons, equip_links)
    payload["detections"] = enriched_persons
    payload["athlete_equipment_links"] = equip_links
    payload["track_activity_profiles"] = activity_profiles

    _write_json(Path(args.output_path), payload)
    return payload


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(description="Generate a SportReel perception sidecar from a configured backend output.")
    parser.add_argument("video_path", help="Input source video path")
    parser.add_argument("output_path", help="Output .perception.json path")
    parser.add_argument("--backend", help="Backend adapter to use, e.g. external_json or ultralytics")
    parser.add_argument("--detections-json", help="External detector/tracker JSON output to normalize")
    parser.add_argument("--ultralytics-model", help="Ultralytics YOLO model path/name; can also use SPORTREEL_ULTRALYTICS_MODEL")
    parser.add_argument("--ultralytics-tracker", help="Ultralytics tracker config; defaults to botsort.yaml for moving-camera/drone footage")
    parser.add_argument("--ultralytics-vid-stride", help="Frame stride for faster long-video tracking; default 10 on CPU runs")
    parser.add_argument("--ultralytics-imgsz", help="Ultralytics inference image size; default 640")
    parser.add_argument("--ultralytics-device", help="Optional Ultralytics device override, e.g. cpu or cuda:0")
    parser.add_argument("--fps", help="FPS override used to derive time_sec for tracker results")
    args = parser.parse_args()

    try:
        backend = (args.backend or "").strip().lower()
        if backend in _ULTRALYTICS_BACKENDS:
            summary = _fast_ultralytics_sidecar(args)
        else:
            summary = generate_sidecar(
                args.video_path,
                args.output_path,
                backend=args.backend,
                detections_json=args.detections_json,
                ultralytics_model=args.ultralytics_model,
                ultralytics_tracker=args.ultralytics_tracker,
                fps=args.fps,
            )
    except Exception as exc:
        print(f"perception sidecar generation failed: {exc}", file=sys.stderr)
        return 1

    status = str(summary.get("status") or "ok").lower()
    stitching = summary.get("track_stitching") if isinstance(summary.get("track_stitching"), dict) else {}
    print(
        f"perception sidecar status={status} detections={len(summary.get('detections', []) or [])} "
        f"equipment={len(summary.get('equipment_detections', []) or [])} "
        f"tracks={stitching.get('raw_track_count', '?')}→{stitching.get('canonical_track_count', '?')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
