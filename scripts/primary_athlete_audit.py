#!/usr/bin/env python3
"""Frame-level primary-athlete audit of the rendered reels (EDL), against the owner's GT athlete boxes.

`actor_correctness.py` gives each window one verdict from the median containment of the tracked person box; a
mid-shot identity switch or a crop that drifts off the athlete does not move a median. This audit walks every
rendered shot of every EDL (what the viewer actually sees) every SAMPLE_STEP source frames and records:

  * which GT athlete the pipeline's subject box lies inside (containment >= CONTAIN_MATCH), per frame;
  * identity switches: changes of that athlete inside one shot;
  * whether the rendered crop shows the shot's primary athlete (>= CROP_VISIBLE of the GT box inside the crop);
  * the GT decision of every rendered frame (include / exclude / no segment);
  * per reel: the GT athletes it shows (mixed reel when > 1); per GT athlete: the reels showing them.

    primary_athlete_audit.py --run-dir DIR --gt-boxes gt_boxes.json [--out FILE] [--md FILE]

`gt_boxes.json` = {source_sha256: {"tracks": [{"athlete_id": id|null, "points": [[frame, x, y, w, h], ...]}],
"segments": [[start, end, decision, usability, reason_codes, athlete_id, event_type], ...]}}. A track without an
athlete_id takes the athlete of the source's only GT athlete when that is unambiguous. Derived from private
footage annotations and NOT committed; only aggregate results are. Inference never reads it.
"""
from __future__ import annotations

import argparse
import bisect
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CONTAIN_MATCH = 0.5   # share of the pipeline's subject box inside a GT athlete box (see actor_correctness.py)
CROP_VISIBLE = 0.5    # share of the GT athlete box inside the rendered crop for the athlete to count as shown
SAMPLE_STEP = 6       # source frames between audited frames (~0.1 s at 59.94 fps)
SUBJECT_MAX_GAP = 12  # a subject sample further than this from the audited frame is "no subject box"
MIN_SHOWN = 0.90      # share of audited frames that must show the primary athlete for a shot to pass
MAX_SWITCHES = 0


def interp(points: list[list[float]], frame: int, max_gap: int = 30):
    frames = [p[0] for p in points]
    i = bisect.bisect_left(frames, frame)
    if i < len(frames) and frames[i] == frame:
        return tuple(points[i][1:5])
    if i == 0 or i == len(points) or points[i][0] - points[i - 1][0] > max_gap:
        return None
    f0, f1 = points[i - 1][0], points[i][0]
    t = (frame - f0) / (f1 - f0)
    return tuple(points[i - 1][k] + t * (points[i][k] - points[i - 1][k]) for k in range(1, 5))


def overlap_share(a: tuple, b: tuple) -> float:
    """Share of box a (x, y, w, h) that lies inside box b."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return (ix * iy) / (aw * ah) if aw * ah > 0 else 0.0


def crop_at(keyframes: list[dict[str, Any]], out_frame: float) -> dict[str, float] | None:
    if not keyframes:
        return None
    ks = sorted(keyframes, key=lambda k: k["out_frame"])
    if out_frame <= ks[0]["out_frame"]:
        return ks[0]["crop"]
    for a, b in zip(ks, ks[1:]):
        if a["out_frame"] <= out_frame <= b["out_frame"]:
            span = b["out_frame"] - a["out_frame"] or 1
            t = (out_frame - a["out_frame"]) / span
            return {k: a["crop"][k] + t * (b["crop"][k] - a["crop"][k]) for k in ("cx", "cy", "w", "h")}
    return ks[-1]["crop"]


def gt_decision(segments: list[list[Any]], frame: int, athlete: str | None = None) -> str:
    """GT decision of `frame` for `athlete` (segments of other athletes do not count; None = any athlete)."""
    hits = [s[2] for s in segments if s[0] <= frame <= s[1] and (athlete is None or s[5] in (athlete, None))]
    if "exclude" in hits:
        return "exclude"
    return "include" if hits else "none"


def resolve_tracks(gt: dict[str, Any]) -> list[dict[str, Any]]:
    seg_athletes = {s[5] for s in gt.get("segments") or [] if s[5]}
    out = []
    for t in gt.get("tracks") or []:
        aid = t.get("athlete_id") or (next(iter(seg_athletes)) if len(seg_athletes) == 1 else None)
        out.append({"athlete_id": aid or "unlabelled", "points": t.get("points") or []})
    return out


def audit_shot(shot: dict[str, Any], gt: dict[str, Any] | None) -> dict[str, Any]:
    src = shot.get("source") or {}
    W, H = float(src.get("width") or 3840), float(src.get("height") or 2160)
    speed = float(shot.get("speed") or 1.0)
    n_out = int(shot["out_end"]) - int(shot["out_start"])
    f0 = int(shot["src_start"])
    f1 = int(round(f0 + n_out * speed))
    row: dict[str, Any] = {"source_file": shot.get("source_file"), "source_sha256": shot.get("source_sha256"),
                           "track_id": shot.get("track_id"), "athlete_ref": shot.get("athlete_ref"),
                           "mode": shot.get("mode"), "src_frames": [f0, f1]}
    if gt is None:
        row["verdict"] = "NO_GT"
        return row
    tracks = resolve_tracks(gt)
    subj = sorted(shot.get("subject_track") or [], key=lambda s: s["src_frame"])
    subj_frames = [s["src_frame"] for s in subj]
    labels: list[str] = []
    sampled: list[int] = []
    shown: dict[str, int] = Counter()
    audited = 0
    frames_with_gt = 0
    for f in range(f0, f1 + 1, SAMPLE_STEP):
        audited += 1
        sampled.append(f)
        gt_now = {t["athlete_id"]: interp(t["points"], f) for t in tracks}
        gt_now = {k: v for k, v in gt_now.items() if v is not None}
        if gt_now:
            frames_with_gt += 1
        label = "no_subject"
        i = bisect.bisect_left(subj_frames, f)
        near = [j for j in (i - 1, i) if 0 <= j < len(subj) and abs(subj_frames[j] - f) <= SUBJECT_MAX_GAP]
        if near:
            b = min((subj[j] for j in near), key=lambda s: abs(s["src_frame"] - f))["bbox"]
            box = (b["x"], b["y"], b["w"], b["h"])
            best = max(((overlap_share(box, g), a) for a, g in gt_now.items()), default=(0.0, None))
            label = best[1] if best[1] and best[0] >= CONTAIN_MATCH else ("other_person" if gt_now else "no_gt_box")
        labels.append(label)
        crop = crop_at(shot.get("keyframes") or [], int(shot["out_start"]) + (f - f0) / speed) or shot.get("crop_start")
        if shot.get("mode") == "contain" or not crop:
            crop_box = (0.0, 0.0, 1.0, 1.0)
        else:
            crop_box = ((crop["cx"] - crop["w"] / 2) / W, (crop["cy"] - crop["h"] / 2) / H, crop["w"] / W, crop["h"] / H)
        for a, g in gt_now.items():
            if overlap_share(g, crop_box) >= CROP_VISIBLE:
                shown[a] += 1
    athlete_labels = [x for x in labels if x not in ("no_subject", "other_person", "no_gt_box")]
    primary = Counter(athlete_labels).most_common(1)[0][0] if athlete_labels else None
    # Decision of each rendered frame for the athlete the shot follows: another athlete's include segment on the
    # same frames is not this reel's include (0094: d805a9b1's ride while the reel stays on 9524ac02).
    decisions = Counter(gt_decision(gt.get("segments") or [], f, primary) for f in sampled)
    switches = sum(1 for a, b in zip(athlete_labels, athlete_labels[1:]) if a != b)
    shown_primary = shown.get(primary, 0) / frames_with_gt if primary and frames_with_gt else 0.0
    others_shown = {a: round(n / audited, 3) for a, n in shown.items() if a != primary and n}
    row.update({"audited_frames": audited, "frames_with_gt_box": frames_with_gt,
                "subject_labels": dict(Counter(labels)), "primary_gt_athlete": primary,
                "identity_switches": switches, "primary_shown_ratio": round(shown_primary, 3),
                "other_gt_athletes_in_crop": others_shown, "gt_decision_frames": dict(decisions)})
    if frames_with_gt < 3:
        row["verdict"] = "UNVERIFIABLE"
    elif primary is None:
        row["verdict"] = "WRONG_PERSON"
    elif switches > MAX_SWITCHES:
        row["verdict"] = "IDENTITY_SWITCH"
    elif shown_primary < MIN_SHOWN:
        row["verdict"] = "PRIMARY_NOT_SHOWN"
    else:
        row["verdict"] = "OK"
    return row


def audit(run_dir: Path, gt_boxes: dict[str, Any]) -> dict[str, Any]:
    reels = []
    for p in sorted((run_dir / "edl").glob("*.edl.json")):
        edl = json.loads(p.read_text())
        shots = [audit_shot(s, gt_boxes.get(s.get("source_sha256"))) for s in edl.get("shots") or []]
        athletes = sorted({s["primary_gt_athlete"] for s in shots if s.get("primary_gt_athlete")})
        reels.append({"output_id": edl.get("output_id"), "shots": shots, "gt_athletes_shown": athletes,
                      "mixed": len(athletes) > 1,
                      "exclude_frames": sum((s.get("gt_decision_frames") or {}).get("exclude", 0) for s in shots),
                      "unsegmented_frames": sum((s.get("gt_decision_frames") or {}).get("none", 0) for s in shots)})
    per_athlete: dict[str, list[str]] = defaultdict(list)
    for r in reels:
        for a in r["gt_athletes_shown"]:
            per_athlete[a].append(r["output_id"])
    shots = [s for r in reels for s in r["shots"]]
    summary = {"reels": len(reels), "shots": len(shots), "verdicts": dict(Counter(s["verdict"] for s in shots)),
               "mixed_reels": sum(r["mixed"] for r in reels),
               "athletes_with_multiple_reels": sorted(a for a, v in per_athlete.items() if len(v) > 1),
               "reels_with_exclude_frames": sum(1 for r in reels if r["exclude_frames"])}
    return {"summary": summary, "reels": reels, "reels_per_gt_athlete": dict(per_athlete)}


def to_markdown(result: dict[str, Any], run_id: str) -> str:
    lines = [f"# Primary-athlete audit of rendered reels — run {run_id}", "",
             "Frame-level, every rendered shot (`scripts/primary_athlete_audit.py`). Not media-verified: this reads "
             "the EDL and the GT boxes; the visual review package is separate.", "",
             "```", json.dumps(result["summary"], indent=1), "```", "",
             "| Reel | Shot source | Track | Verdict | Primary GT athlete | Switches | Shown | Other athletes in crop | GT frames (inc/exc/none) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in result["reels"]:
        for s in r["shots"]:
            d = s.get("gt_decision_frames") or {}
            lines.append(f"| {r['output_id'][-24:]} | {str(s['source_file'])[-11:-4]} | {s['track_id']} | {s['verdict']} | "
                         f"{(s.get('primary_gt_athlete') or '-')[:8]} | {s.get('identity_switches', '-')} | "
                         f"{s.get('primary_shown_ratio', '-')} | "
                         f"{', '.join(f'{k[:8]}:{v}' for k, v in (s.get('other_gt_athletes_in_crop') or {}).items()) or '-'} | "
                         f"{d.get('include', 0)}/{d.get('exclude', 0)}/{d.get('none', 0)} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--gt-boxes", required=True, type=Path)
    ap.add_argument("--run-id", default="")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--md", type=Path)
    a = ap.parse_args(argv)
    result = audit(a.run_dir, json.loads(a.gt_boxes.read_text()))
    print(json.dumps(result["summary"]))
    if a.out:
        a.out.write_text(json.dumps(result, indent=1))
    if a.md:
        a.md.write_text(to_markdown(result, a.run_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
