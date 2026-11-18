#!/usr/bin/env python3
"""Athlete x Ride x Pipeline-stage matrix (cycle 6, base measurement for the four coverage/cardinality problems).

For every GT ride it follows the same frames from the source to the rendered reel and names the first stage where
frames were lost:

    detection/tracking -> candidate event -> selected event -> rendered window -> reel (publishable? QA? state?)

and for every GT athlete it answers the four product questions with evidence, never with a total:
  A  missing    - GT rides not fully present in any reel, and the first stage that lost them
  B  extra      - frames inside a GT `exclude` range that reached a reel
  C  split      - the athlete's rides spread over more than one reel (or a reel holding another athlete)
  D  no reel    - athlete with GT rides and no reel at all (blocked with a reason, or silently absent)

Inputs are the frozen run artifacts (publishable_reel_manifest.json + predictions.v1.json). GT is read, never
changed. The ride unit is gt_scorecard's heuristic (same athlete, include segments <= 3 frames apart, PQ-19).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import gt_scorecard as sc  # noqa: E402

TRACK_BRIDGE_SEC = 0.5          # consecutive track samples closer than this count as continuous presence


def _spans_from_samples(frames: list[int], bridge: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for f in sorted(set(frames)):
        if spans and f - spans[-1][1] <= bridge:
            spans[-1] = (spans[-1][0], f)
        else:
            spans.append((f, f))
    return spans


def _cov(spans: list[tuple[int, int]], lo: int, hi: int) -> int:
    return sc._len(sc._clip(sc._union(spans), lo, hi))


def _source_index(predictions: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["source_sha256"]: s for s in (predictions or {}).get("sources") or [] if s.get("source_sha256")}


def build(gt: dict[str, Any], manifest: dict[str, Any], predictions: dict[str, Any]) -> dict[str, Any]:
    truth = sc.load_gt(gt)
    sources = _source_index(predictions)
    parts, blocked = sc.rendered_windows(manifest, predictions)

    # reel facts from the manifest
    reel_info: dict[str, dict[str, Any]] = {}
    for arow in manifest.get("athletes") or []:
        for part in arow.get("parts") or []:
            key = f"{arow.get('athlete_key')}#{part.get('part_index')}"
            reel_info[key] = {
                "publishable": part.get("publishable") is True, "qa_verdict": part.get("qa_verdict"),
                "state": part.get("state"), "business_outcome": arow.get("business_outcome"),
                "blocking_reasons": [str(x) for x in (arow.get("blocking_reasons") or [])],
                "athlete_key": arow.get("athlete_key")}

    # rendered spans per (ride, reel) and excluded frames per reel
    ride_reel: dict[str, dict[str, list[tuple[int, int]]]] = defaultdict(lambda: defaultdict(list))
    reel_excluded: dict[str, int] = defaultdict(int)
    reel_athletes: dict[str, set[str]] = defaultdict(set)
    for part in parts:
        by_src: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for w in part["windows"]:
            src = truth.get(w["sha"])
            if not src:
                continue
            fps = src["fps"]
            a, b = int(round(w["a_sec"] * fps)), int(round(w["b_sec"] * fps))
            by_src[w["sha"]].append((a, b))
            for r in src["rides"]:
                ov = sc._overlap(a, b, r["start_frame"], r["end_frame"])
                if ov and (ov >= sc.ATTRIBUTION_SHARE * max(1, b - a) or ov > sc.ATTRIBUTION_SEC * fps):
                    reel_athletes[part["key"]].add(r["athlete_id"])
                if ov:
                    ride_reel[r["ride_uid"]][part["key"]].append((max(a, r["start_frame"]), min(b, r["end_frame"])))
        for sha, spans in by_src.items():
            for ex in truth[sha]["excludes"]:
                reel_excluded[part["key"]] += sc._len(sc._clip(sc._union(spans), ex[0], ex[1]))

    rows: list[dict[str, Any]] = []
    for sha, src in truth.items():
        pred = sources.get(sha) or {}
        fps = src["fps"]
        bridge = int(round(TRACK_BRIDGE_SEC * fps))
        track_frames = [int(s["src_frame"]) for t in pred.get("tracks") or [] for s in t.get("samples") or []
                        if "src_frame" in s]
        presence = _spans_from_samples(track_frames, bridge)
        for r in src["rides"]:
            lo, hi = r["start_frame"], r["end_frame"]
            span = max(1, hi - lo)
            cands, cand_spans, sel_spans = [], [], []
            for ev in pred.get("events") or []:
                a, b = ev.get("start_frame"), ev.get("end_frame")
                if a is None or b is None or not sc._overlap(int(a), int(b), lo, hi):
                    continue
                cands.append({"candidate_id": ev.get("candidate_id"), "type": ev.get("event_type"),
                              "decision": ev.get("decision"), "reason": ev.get("reason"),
                              "frames": [int(a), int(b)], "athlete_key": ev.get("athlete_key")})
                cand_spans.append((int(a), int(b)))
                if ev.get("decision") == "selected":
                    sel_spans.append((int(a), int(b)))
            reels = {k: sc._len(sc._union(v)) for k, v in ride_reel.get(r["ride_uid"], {}).items()}
            rendered = sc._union([s for v in ride_reel.get(r["ride_uid"], {}).values() for s in v])
            row = {
                "ride_uid": r["ride_uid"], "athlete_id": r["athlete_id"], "source_sha256": sha,
                "source_video": pred.get("source_video"), "frames": [lo, hi], "fps": round(fps, 3),
                "ride_sec": round(span / fps, 2),
                "track_presence_frac": round(_cov(presence, lo, hi) / span, 3),
                "candidate_frac": round(_cov(cand_spans, lo, hi) / span, 3),
                "selected_frac": round(_cov(sel_spans, lo, hi) / span, 3),
                "rendered_frac": round(sc._len(rendered) / span, 3),
                "candidates": cands, "reels": {k: round(v / span, 3) for k, v in reels.items()},
            }
            s_err = abs(rendered[0][0] - lo) / fps if rendered else None      # unrounded, as gt_scorecard decides FULL
            e_err = abs(rendered[-1][1] - hi) / fps if rendered else None
            row["rendered_start_err_sec"] = round(s_err, 2) if rendered else None
            row["rendered_end_err_sec"] = round(e_err, 2) if rendered else None
            row["full"] = bool(rendered) and sc._len(rendered) >= span - 2 * sc.BOUNDARY_TOLERANCE_SEC * fps \
                and s_err <= sc.BOUNDARY_TOLERANCE_SEC and e_err <= sc.BOUNDARY_TOLERANCE_SEC
            row["first_loss_stage"] = _first_loss(row)
            rows.append(row)

    excluded_union = 0
    for sha, src in truth.items():
        allw = [(int(round(w["a_sec"] * src["fps"])), int(round(w["b_sec"] * src["fps"])))
                for p in parts for w in p["windows"] if w["sha"] == sha]
        for ex in src["excludes"]:
            excluded_union += sc._len(sc._clip(sc._union(allw), ex[0], ex[1]))
    athletes = _athletes(rows, reel_info, reel_athletes, reel_excluded)
    return {"schema": "athlete-ride-matrix-v1", "run_id": manifest.get("pipeline_run_id"),
            "gt_digest": gt.get("digest"), "ride_unit": "HEURISTIC_same_athlete_include_gap_le_3_frames",
            "rides": rows, "athletes": athletes, "blocked_windows": len(blocked),
            "summary": dict(_summary(rows, athletes), B_excluded_frames_union=excluded_union)}


def _first_loss(row: dict[str, Any]) -> str:
    """The earliest stage whose coverage is already below what a full ride needs (>= 0.95)."""
    if row["full"]:
        return "none"
    # Candidate events come from the analyzer (video understanding); tracks are a separate framing/QA signal, so the
    # chain is candidate -> selection -> render, and track presence is reported beside it, not before it.
    if row["candidate_frac"] < 0.95:
        return "event_candidate_window" if row["candidate_frac"] > 0 else "action_analysis_no_candidate"
    if row["selected_frac"] < row["candidate_frac"] - 0.02:
        reasons = sorted({c["reason"] for c in row["candidates"] if c["decision"] != "selected"})
        return "selection_dedup:" + ",".join(reasons or ["unspecified"])
    if row["selected_frac"] < 0.95:
        return "event_candidate_window"
    if row["rendered_frac"] < row["selected_frac"] - 0.02:
        return "editor_render"
    return "boundaries_start_end"


def _athletes(rows, reel_info, reel_athletes, reel_excluded) -> list[dict[str, Any]]:
    by_ath: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_ath[r["athlete_id"]].append(r)
    out = []
    for ath, rides in sorted(by_ath.items()):
        reel_keys = sorted({k for r in rides for k in r["reels"]})
        full = [r for r in rides if r["full"]]
        info = [dict(key=k, **reel_info.get(k, {}), excluded_frames=reel_excluded.get(k, 0),
                     other_athletes=sorted(reel_athletes.get(k, set()) - {ath})) for k in reel_keys]
        status = ("NO_REEL" if not reel_keys else
                  "SPLIT" if len(reel_keys) > 1 else
                  "MIXED" if info and info[0]["other_athletes"] else "ONE_REEL")
        outcome = ("publishable" if any(i.get("publishable") for i in info) else
                   "reel_blocked" if info else "no_reel")
        out.append({"athlete_id": ath, "gt_rides": len(rides), "rides_full": len(full),
                    "rides_missing_or_partial": [r["ride_uid"] for r in rides if not r["full"]],
                    "rides_not_in_any_reel": [r["ride_uid"] for r in rides if not r["reels"]],
                    "reels": info, "cardinality": status, "outcome": outcome,
                    "excluded_frames_in_reels": sum(i["excluded_frames"] for i in info),
                    "d_no_reel_silent": (not reel_keys),
                    })
    return out


def _summary(rows, athletes) -> dict[str, Any]:
    loss: dict[str, int] = defaultdict(int)
    for r in rows:
        if not r["full"]:
            loss[r["first_loss_stage"].split(":")[0]] += 1
    return {
        "gt_athletes": len(athletes), "gt_rides": len(rows), "rides_full": sum(r["full"] for r in rows),
        "A_rides_not_full": sum(not r["full"] for r in rows),
        "A_rides_in_no_reel": sum(not r["reels"] for r in rows),
        "A_first_loss_by_stage": dict(sorted(loss.items())),
        "B_athletes_with_excluded_frames": sum(a["excluded_frames_in_reels"] > 0 for a in athletes),
        "B_excluded_frames_total": sum(a["excluded_frames_in_reels"] for a in athletes),
        "C_split_athletes": sum(a["cardinality"] == "SPLIT" for a in athletes),
        "C_mixed_reel_athletes": sum(a["cardinality"] == "MIXED" for a in athletes),
        "D_athletes_without_reel": sum(a["cardinality"] == "NO_REEL" for a in athletes),
        "athletes_publishable": sum(a["outcome"] == "publishable" for a in athletes),
        "athletes_reel_blocked": sum(a["outcome"] == "reel_blocked" for a in athletes),
    }


def markdown(m: dict[str, Any]) -> str:
    s = m["summary"]
    lines = [f"# Athlete x Ride x Stage matrix - run {m['run_id']}", "",
             "GT digest `%s`; ride unit = heuristic (PQ-19). Fractions are of the GT ride's frames." % m["gt_digest"][:12], "",
             "## Summary", "", "```json", json.dumps(s, indent=1), "```", "",
             "## Athletes", "", "| GT athlete | rides | full | reels | cardinality | outcome | excluded fr. | rides missing/partial |",
             "|---|---:|---:|---:|---|---|---:|---|"]
    for a in m["athletes"]:
        lines.append(f"| {a['athlete_id'][:8]} | {a['gt_rides']} | {a['rides_full']} | {len(a['reels'])} | "
                     f"{a['cardinality']} | {a['outcome']} | {a['excluded_frames_in_reels']} | "
                     f"{', '.join(u.split('#')[0][:6] + '#' + u.split('#')[1] for u in a['rides_missing_or_partial']) or '-'} |")
    lines += ["", "## Rides", "",
              "| ride | athlete | video | sec | track | cand | sel | rend | start/end err s | first loss | reels (frac) |",
              "|---|---|---|---:|---:|---:|---:|---:|---|---|---|"]
    for r in m["rides"]:
        reels = ", ".join(f"{k.split('#')[0][-6:]}#{k.split('#')[1]}:{v}" for k, v in r["reels"].items()) or "-"
        vid = (r["source_video"] or "")[-14:-6]
        lines.append(f"| {r['ride_uid']} | {r['athlete_id'][:8]} | {vid} | {r['ride_sec']} | {r['track_presence_frac']} | "
                     f"{r['candidate_frac']} | {r['selected_frac']} | {r['rendered_frac']} | "
                     f"{r['rendered_start_err_sec']}/{r['rendered_end_err_sec']} | {r['first_loss_stage']} | {reels} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default=str(ROOT / "evaluation/ground_truth/gtv1_frozen.json"))
    ap.add_argument("--run-dir", required=True, help="dir with publishable_reel_manifest.json and predictions.v1.json")
    ap.add_argument("--out", required=True, help="output base path (writes .json and .md)")
    args = ap.parse_args(argv)
    run = Path(args.run_dir)
    m = build(sc._load(Path(args.gt)), sc._load(run / "publishable_reel_manifest.json"),
              sc._load(run / "predictions.v1.json"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(m, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    out.with_suffix(".md").write_text(markdown(m), encoding="utf-8")
    print(json.dumps(m["summary"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
