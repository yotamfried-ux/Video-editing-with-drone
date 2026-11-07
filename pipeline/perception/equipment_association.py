"""Sports equipment detection normalization and athlete-equipment association (OPT-01).

Links detected sports equipment (surfboards, bicycles, skateboards, snowboards, skis,
sports balls, kites, etc.) to tracked athletes across frames using spatial proximity
(IoU and normalized center distance) and temporal continuity.

Also classifies each person track into one of three activity states:
  - "active": sustained movement or active equipment interaction
  - "waiting": stationary/near-stationary (e.g. sitting in the lineup waiting)
  - "background_passerby": brief or peripheral appearance without athletic engagement

Safety invariant: Equipment association is supporting evidence for active-athlete
selection and structured attribute enrichment, NEVER sole proof of cross-video identity.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Mapping

SPORTS_EQUIPMENT_CLASSES: dict[int, str] = {
    1: "bicycle",
    3: "motorcycle",
    8: "boat",
    24: "backpack",
    30: "skis",
    31: "snowboard",
    32: "sports ball",
    33: "kite",
    36: "skateboard",
    37: "surfboard",
}

SPORT_RELEVANT_EQUIPMENT: dict[str, set[str]] = {
    "surfing": {"surfboard", "boat", "kite"},
    "skateboarding": {"skateboard", "backpack"},
    "cycling": {"bicycle", "backpack"},
    "mountain_biking": {"bicycle", "backpack"},
    "snowboarding": {"snowboard", "skis", "backpack"},
    "skiing": {"skis", "snowboard", "backpack"},
    "football": {"sports ball"},
    "soccer": {"sports ball"},
    "basketball": {"sports ball"},
    "kitesurfing": {"kite", "surfboard"},
}

ALL_DETECTION_CLASS_IDS: list[int] = sorted([0, *SPORTS_EQUIPMENT_CLASSES.keys()])


def can_use_equipment_as_sole_identity_proof() -> bool:
    """Equipment may be shared, rented, or similar; never use as sole identity proof."""
    return False


def is_equipment_class(class_id: int | None, class_name: str | None = None) -> bool:
    if class_id is not None and int(class_id) in SPORTS_EQUIPMENT_CLASSES:
        return True
    if class_name:
        norm = str(class_name).strip().lower()
        return norm in set(SPORTS_EQUIPMENT_CLASSES.values())
    return False


def _bbox(item: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    raw = item.get("bbox_xyxy") or item.get("xyxy")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _iou(box_a: tuple[float, float, float, float], box_b: tuple[float, float, float, float]) -> float:
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0.0:
        return 0.0
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    denom = area_a + area_b - inter
    return inter / denom if denom > 0.0 else 0.0


def _person_equipment_affinity(
    person_box: tuple[float, float, float, float],
    equip_box: tuple[float, float, float, float],
    frame_w: float,
    frame_h: float,
) -> float:
    """Compute spatial affinity in [0, 1] between a person bbox and an equipment bbox.

    In surfing/skate/bike/snow footage, the board/bike is typically directly underneath
    or overlapping the lower half of the athlete's bounding box.
    """
    overlap = _iou(person_box, equip_box)
    px = (person_box[0] + person_box[2]) / 2.0
    py_bottom = person_box[1] * 0.35 + person_box[3] * 0.65
    ex = (equip_box[0] + equip_box[2]) / 2.0
    ey = (equip_box[1] + equip_box[3]) / 2.0

    person_diag = max(24.0, math.hypot(person_box[2] - person_box[0], person_box[3] - person_box[1]))
    equip_diag = max(24.0, math.hypot(equip_box[2] - equip_box[0], equip_box[3] - equip_box[1]))
    scale = max(person_diag, equip_diag, 0.06 * math.hypot(max(1.0, frame_w), max(1.0, frame_h)))

    dist = math.hypot(px - ex, py_bottom - ey)
    norm_dist = dist / scale
    if norm_dist > 1.75 and overlap <= 0.0:
        return 0.0

    proximity = max(0.0, 1.0 - (norm_dist / 1.75))
    return round(min(1.0, 0.55 * proximity + 0.45 * min(1.0, overlap * 3.0)), 4)


def associate_equipment_with_athletes(
    person_detections: list[dict[str, Any]],
    equipment_detections: list[dict[str, Any]],
    *,
    min_affinity: float = 0.25,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Link equipment detections to person detections per frame without double-assigning one board to two athletes.

    Returns:
      - enriched_person_detections: person detections with optional `associated_equipment` field
      - athlete_equipment_links: summary per person `track_id`
    """
    if not person_detections:
        return [], {}

    equip_by_frame: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for eq in equipment_detections or []:
        if isinstance(eq, dict) and eq.get("frame_index") is not None:
            equip_by_frame[int(eq["frame_index"])].append(eq)

    persons_by_frame: dict[int, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    copied_persons: list[dict[str, Any]] = [dict(p) for p in person_detections]
    for idx, person in enumerate(copied_persons):
        f_idx = int(person.get("frame_index") or 0)
        persons_by_frame[f_idx].append((idx, person))

    track_equip_counts: dict[str, Counter[str]] = defaultdict(Counter)
    track_equip_ids: dict[str, set[str]] = defaultdict(set)
    track_affinities: dict[str, list[float]] = defaultdict(list)
    track_frame_counts: Counter[str] = Counter()

    for person in copied_persons:
        tid = person.get("track_id")
        if tid is not None:
            track_frame_counts[str(tid)] += 1

    for f_idx, frame_persons in persons_by_frame.items():
        frame_equips = equip_by_frame.get(f_idx, [])
        if not frame_equips:
            continue

        candidates: list[tuple[float, int, int]] = []
        for p_list_idx, (global_p_idx, p_det) in enumerate(frame_persons):
            p_box = _bbox(p_det)
            if p_box is None:
                continue
            fw = float(p_det.get("frame_width") or 1920.0)
            fh = float(p_det.get("frame_height") or 1080.0)
            for eq_idx, eq_det in enumerate(frame_equips):
                e_box = _bbox(eq_det)
                if e_box is None:
                    continue
                aff = _person_equipment_affinity(p_box, e_box, fw, fh)
                if aff >= min_affinity:
                    candidates.append((aff, global_p_idx, eq_idx))

        # Greedy bipartite matching from highest affinity down so two nearby surfers
        # cannot claim the exact same surfboard instance in the same frame.
        candidates.sort(key=lambda item: item[0], reverse=True)
        claimed_persons: set[int] = set()
        claimed_equips: set[int] = set()
        for aff, global_p_idx, eq_idx in candidates:
            if global_p_idx in claimed_persons or eq_idx in claimed_equips:
                continue
            claimed_persons.add(global_p_idx)
            claimed_equips.add(eq_idx)
            eq_det = frame_equips[eq_idx]
            eq_class_id = eq_det.get("class_id")
            eq_name = str(
                eq_det.get("class_name")
                or SPORTS_EQUIPMENT_CLASSES.get(int(eq_class_id) if eq_class_id is not None else -1, "equipment")
            ).lower()
            eq_tid = eq_det.get("track_id")
            copied_persons[global_p_idx]["associated_equipment"] = {
                "class_id": eq_class_id,
                "class_name": eq_name,
                "equipment_track_id": eq_tid,
                "affinity": aff,
                "bbox_xyxy": list(eq_det.get("bbox_xyxy") or []),
            }
            p_tid = copied_persons[global_p_idx].get("track_id")
            if p_tid is not None:
                tid_str = str(p_tid)
                track_equip_counts[tid_str][eq_name] += 1
                if eq_tid is not None:
                    track_equip_ids[tid_str].add(f"{eq_name}:{eq_tid}")
                track_affinities[tid_str].append(aff)

    links: dict[str, dict[str, Any]] = {}
    for tid_str, total_frames in track_frame_counts.items():
        counts = track_equip_counts.get(tid_str)
        if not counts:
            continue
        primary_equip, equip_frames = counts.most_common(1)[0]
        affs = track_affinities[tid_str]
        links[tid_str] = {
            "primary_equipment": primary_equip,
            "equipment_counts": dict(counts),
            "equipment_track_ids": sorted(track_equip_ids[tid_str]),
            "associated_frames": sum(counts.values()),
            "total_track_frames": total_frames,
            "equipment_association_ratio": round(sum(counts.values()) / max(1, total_frames), 4),
            "mean_affinity": round(sum(affs) / max(1, len(affs)), 4),
            "sole_identity_proof_allowed": False,
        }

    return copied_persons, links


def classify_track_activity_profiles(
    person_detections: list[dict[str, Any]],
    equipment_links: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Classify each person track into 'active', 'waiting', or 'background_passerby'."""
    by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for det in person_detections or []:
        tid = det.get("track_id")
        if tid is not None:
            by_track[str(tid)].append(det)

    profiles: dict[str, dict[str, Any]] = {}
    links = equipment_links or {}

    for tid, dets in by_track.items():
        ordered = sorted(dets, key=lambda d: float(d.get("time_sec") or 0.0))
        n = len(ordered)
        cxs: list[float] = []
        cys: list[float] = []
        areas: list[float] = []
        edge_Distances: list[float] = []
        step_velocities: list[float] = []

        for idx, d in enumerate(ordered):
            box = _bbox(d)
            fw = max(1.0, float(d.get("frame_width") or 1920.0))
            fh = max(1.0, float(d.get("frame_height") or 1080.0))
            if box is None:
                continue
            cx = ((box[0] + box[2]) / 2.0) / fw
            cy = ((box[1] + box[3]) / 2.0) / fh
            cxs.append(cx)
            cys.append(cy)
            area = ((box[2] - box[0]) * (box[3] - box[1])) / (fw * fh)
            areas.append(area)
            edge_dist = min(cx, 1.0 - cx, cy, 1.0 - cy)
            edge_Distances.append(edge_dist)
            if idx > 0 and len(cxs) >= 2:
                dt = max(0.033, float(d.get("time_sec") or 0.0) - float(ordered[idx - 1].get("time_sec") or 0.0))
                step = math.hypot(cxs[-1] - cxs[-2], cys[-1] - cys[-2])
                if dt <= 2.5:
                    step_velocities.append(step / dt)

        disp = math.hypot(max(cxs) - min(cxs), max(cys) - min(cys)) if cxs else 0.0
        mean_vel = sum(step_velocities) / len(step_velocities) if step_velocities else 0.0
        mean_edge = sum(edge_Distances) / len(edge_Distances) if edge_Distances else 0.5
        mean_area = sum(areas) / len(areas) if areas else 0.0
        duration = (
            max(0.0, float(ordered[-1].get("time_sec") or 0.0) - float(ordered[0].get("time_sec") or 0.0))
            if n >= 2
            else 0.0
        )
        eq_info = links.get(tid) or {}
        eq_ratio = float(eq_info.get("equipment_association_ratio") or 0.0)
        primary_eq = eq_info.get("primary_equipment")

        if n < 3 and duration < 1.5 and eq_ratio == 0.0 and disp < 0.08:
            state = "background_passerby"
        elif mean_edge < 0.05 and n < 5 and eq_ratio == 0.0:
            state = "background_passerby"
        elif disp >= 0.10 or mean_vel >= 0.035 or (eq_ratio >= 0.20 and disp >= 0.045):
            state = "active"
        elif disp < 0.055 and mean_vel < 0.02:
            state = "waiting"
        else:
            state = "active" if (eq_ratio > 0.0 or n >= 4) else "background_passerby"

        activity_score = round(
            min(
                1.0,
                0.45 * min(1.0, disp / 0.22)
                + 0.25 * min(1.0, mean_vel / 0.06)
                + 0.20 * min(1.0, eq_ratio * 1.5)
                + 0.10 * min(1.0, mean_edge / 0.20),
            ),
            4,
        )
        profiles[tid] = {
            "track_id": tid,
            "activity_state": state,
            "activity_score": activity_score,
            "displacement": round(disp, 4),
            "mean_velocity": round(mean_vel, 4),
            "duration_sec": round(duration, 2),
            "detection_count": n,
            "mean_area_ratio": round(mean_area, 5),
            "primary_equipment": primary_eq,
            "equipment_association_ratio": round(eq_ratio, 4),
        }

    return profiles


__all__ = [
    "ALL_DETECTION_CLASS_IDS",
    "SPORTS_EQUIPMENT_CLASSES",
    "SPORT_RELEVANT_EQUIPMENT",
    "associate_equipment_with_athletes",
    "can_use_equipment_as_sole_identity_proof",
    "classify_track_activity_profiles",
    "is_equipment_class",
]
