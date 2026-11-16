#!/usr/bin/env python3
"""Offline review package for cases where the pipeline and the frozen Ground Truth disagree.

Evaluation only. GT is read from a JSON file given on the command line (exported read-only from
ground_truth.*); it is never imported by the pipeline and never influences inference. Output goes to a local
directory or a CI artifact, never to production.

For each disputed source: the GT segments (seconds and frames), what the analyzer said (window, score,
description), what was rendered (EDL source window, bound track), the identity cluster, the publication state,
and the class of disagreement. Visual proof needs the video; every case is marked VISUAL_REVIEW_REQUIRED.

Usage: build_gt_review_package.py --diagnostics DIR --gt GT.json --out OUT_DIR [--sources 0095,0155,0108]
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path
from typing import Any


def _src(text: str) -> str:
    match = re.search(r"_(\d{4})_D", str(text))
    return match.group(1) if match else str(text)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build(diagnostics: Path, gt: list[dict[str, Any]], wanted: set[str]) -> list[dict[str, Any]]:
    ledger = _load(diagnostics / "candidate_decision_ledger.json").get("candidates", [])
    trace = _load(diagnostics / "identity_trace.json")
    manifest = _load(diagnostics / "publishable_reel_manifest.json")
    shots = []
    for path in sorted(glob.glob(str(diagnostics / "edl" / "*.edl.json"))):
        edl = _load(Path(path))
        for shot in edl.get("shots", []):
            shots.append({**shot, "_reel": edl.get("output_id")})
    # A source can hold several athletes, so it can belong to several clusters: keep all of them.
    clusters: dict[str, dict[str, Any]] = {}
    for layer in ("model", "compile"):
        for cluster in trace.get("layers", {}).get(layer, []):
            members = sorted({_src(m) for m in cluster.get("members", [])})
            for member in members:
                entry = clusters.setdefault(member, {"model": [], "compile": [], "gates": []})
                entry[layer].append(members)
                if layer == "compile":
                    entry["gates"].append((cluster.get("flags") or {}).get("_identity_gate_reason"))
    published: dict[str, list[dict[str, Any]]] = {}
    for row in manifest.get("athletes", []):
        sources = sorted({_src(item) for item in row.get("action_lineage", [])})
        for source in sources:
            published.setdefault(source, []).append({
                "reel_sources": sources, "publishable": [part.get("publishable") for part in row.get("parts", [])]})
    # GT athlete labels per source, to compare identity across sources with the pipeline's final clusters.
    gt_athletes = {g["src"][:4]: {seg.get("athlete") for seg in g.get("segments") or [] if seg.get("athlete")} for g in gt}

    out = []
    for g in gt:
        source = g["src"][:4]
        if wanted and source not in wanted:
            continue
        fps = float(g["fps_num"]) / float(g["fps_den"])
        gt_segments = [{
            "start_sec": round(int(seg["start_frame"]) / fps, 2), "end_sec": round(int(seg["end_frame"]) / fps, 2),
            "decision": seg["decision"], "usability": seg["usability"], "reasons": seg.get("reasons") or [],
            "athlete_label": seg.get("athlete"),
        } for seg in g.get("segments") or []]
        candidates = [{
            "selected": c.get("selected"), "score": c.get("score"), "type": c.get("event_type"),
            "window": c.get("source_window"), "discard": c.get("discard_cause"), "description": c.get("description"),
        } for c in ledger if _src(c.get("source_video", "")) == source]
        rendered = []
        for shot in shots:
            if _src(shot.get("source_file", "")) != source:
                continue
            fps_src = float((shot.get("source") or {}).get("fps") or fps)
            start = shot["src_start"] / fps_src
            # Output frames at 30 fps play source time at normal speed (speed = source frames per output frame).
            length = (shot["out_end"] - shot["out_start"]) / 30.0
            rendered.append({"reel": shot["_reel"], "event_id": shot.get("event_id"), "track_id": shot.get("track_id"),
                             "src_start_sec": round(start, 2), "src_end_sec": round(start + length, 2)})
        included = [s for s in gt_segments if s["decision"] == "include"]
        excluded = [s for s in gt_segments if s["decision"] == "exclude"]
        kinds = []
        if excluded and rendered:
            for seg in excluded:
                if any(r["src_start_sec"] < seg["end_sec"] and r["src_end_sec"] > seg["start_sec"] for r in rendered):
                    kinds.append("usability" if seg["start_sec"] <= 0.1 else "event_boundary")
        if included and not rendered:
            kinds.append("action_missed")
        cluster = clusters.get(source, {})
        final = {m for members in cluster.get("compile", []) for m in members} or {source}
        for other, labels in gt_athletes.items():
            if other == source:
                continue
            same_gt = bool(labels & gt_athletes.get(source, set()))
            same_cluster = other in final
            if same_gt and not same_cluster:
                kinds.append(f"identity_missed_merge:{other}")
            elif same_cluster and not same_gt and labels:
                kinds.append(f"identity_wrong_merge:{other}")
        out.append({
            "source": source, "source_sha256": g.get("sha256"), "duration_sec": round(g["duration_ms"] / 1000, 2),
            "gt_segments": gt_segments, "analyzer_candidates": candidates, "rendered_shots": rendered,
            "identity": cluster, "publishable": published.get(source),
            "disagreement": sorted(set(kinds)) or ["none_detected_offline"],
            "status": "VISUAL_REVIEW_REQUIRED",
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostics", required=True, type=Path)
    parser.add_argument("--gt", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sources", default="")
    args = parser.parse_args()
    wanted = {s.strip() for s in args.sources.split(",") if s.strip()}
    cases = build(args.diagnostics, _load(args.gt), wanted)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "gt_review_package.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding="utf-8")
    for case in cases:
        print(f"{case['source']}: {', '.join(case['disagreement'])} | publishable={case['publishable']} | "
              f"identity={case['identity'].get('compile')} | rendered={[(r['src_start_sec'], r['src_end_sec']) for r in case['rendered_shots']]} | "
              f"gt={[(s['start_sec'], s['end_sec'], s['decision']) for s in case['gt_segments']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
