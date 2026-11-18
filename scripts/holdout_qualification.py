#!/usr/bin/env python3
"""Independent holdout qualification (cycle 12): freeze a holdout GT and a locked candidate, then evaluate it.

Why: FIX-PQ-11-001 (motion-supported onset) improved the 24 GT-v1 sources it was developed on. Generalisation needs
NEW sources that took no part in development, calibration, prompt choice, replays or algorithm selection.

  freeze   --gt HOLDOUT_GT.json --conditions CONDITIONS.json --id H1 --out-dir evaluation/ground_truth/holdout/H1
           [--dev-gt evaluation/ground_truth/gtv1_frozen.json ...] [--dev-sha-file FILE ...] --budget-cap USD
           --metrics PREREG.json
      Refuses when ANY holdout source SHA-256 is in a development set (GT-v1 and any listed set), when a member has
      no reviewed range, or when the budget cap is missing. Writes frozen.json (holdout GT, digest) and lock.json:
      code SHA, digest of every sport profile's thresholds (OnsetPolicy etc.), digests of the prompt sources, the
      pre-registered metrics/thresholds, the source hashes, the budget cap. A lock is immutable: an existing lock is
      never overwritten.
  verify-lock --lock lock.json
      Exit 1 when the current code's thresholds or prompt digests differ from the lock (tuning after the freeze).
  evaluate --frozen frozen.json --lock lock.json --diagnostics DIR [--out OUT.json]
      Normalised metrics (rates per ride, seconds per ride-minute, per reel-minute) overall and stratified by athlete,
      action type, every condition tag (lighting, distance, crowding, camera motion, difficulty...), plus the
      pre-registered pass/fail table. Absolute counts are reported but never compared across sets of different size.

conditions.json: {"<sha256>": {"lighting": "low_sun", "distance": "far", "crowding": "multi", "camera_motion":
"orbit", "difficulty": "hard", "action_types": ["early_paddle", "fast_start"]}, ...}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import gt_scorecard as gs  # noqa: E402

PROMPT_SOURCES = ["pipeline/stages/analyzer.py", "pipeline/stages/identity.py", "pipeline/performance_reel_policy.py",
                  "pipeline/identity_pair_consensus.py"]
REQUIRED_TAGS = ("lighting", "distance", "crowding", "camera_motion", "difficulty")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def profile_thresholds() -> dict:
    from pipeline.sport_profiles import all_profiles

    out = {}
    for p in all_profiles():
        out[p.profile_id] = {"onset": vars(p.onset), "coverage_first": p.coverage_first,
                             "framing_subject_height_ratio": p.framing_subject_height_ratio,
                             "failed_attempt_terms": sorted(p.failed_attempt_terms), "event_terms": sorted(p.event_terms)}
    return out


def code_state() -> dict:
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    except OSError:
        sha = ""
    return {"code_sha": sha,
            "thresholds_sha256": _sha(_canon(profile_thresholds())),
            "prompt_sources_sha256": {p: _sha((ROOT / p).read_bytes()) for p in PROMPT_SOURCES if (ROOT / p).exists()}}


def dev_shas(dev_gts: list[Path], sha_files: list[Path]) -> set[str]:
    out: set[str] = set()
    for p in dev_gts:
        out |= {m["sha256"] for m in json.loads(p.read_text()).get("members") or []}
    for p in sha_files:
        out |= {line.strip() for line in p.read_text().splitlines() if len(line.strip()) == 64}
    return out


def freeze(gt_path: Path, cond_path: Path, hid: str, out_dir: Path, dev_gt: list[Path], dev_sha_files: list[Path],
           budget_cap: float | None, metrics_path: Path) -> int:
    gt = json.loads(gt_path.read_text())
    cond = json.loads(cond_path.read_text())
    members = gt.get("members") or []
    problems = []
    shas = [m.get("sha256", "") for m in members]
    overlap = sorted(set(shas) & dev_shas(dev_gt, dev_sha_files))
    if overlap:
        problems.append(f"{len(overlap)} holdout source(s) are development data: {[s[:12] for s in overlap]}")
    if not members:
        problems.append("holdout GT has no members")
    for m in members:
        c = m.get("content") or {}
        c = json.loads(c) if isinstance(c, str) else c
        if not c.get("reviewed_ranges"):
            problems.append(f"{m.get('sha256', '')[:12]}: no reviewed range")
        missing = [t for t in REQUIRED_TAGS if t not in (cond.get(m.get("sha256")) or {})]
        if missing:
            problems.append(f"{m.get('sha256', '')[:12]}: condition tags missing {missing}")
    if len(set(shas)) != len(shas):
        problems.append("duplicate source in the holdout")
    if budget_cap is None or budget_cap <= 0:
        problems.append("a hard budget cap is required")
    metrics = json.loads(metrics_path.read_text())
    if not metrics.get("success") or not metrics.get("protected"):
        problems.append("pre-registered metrics need 'success' and 'protected' thresholds")
    lock_path = out_dir / "lock.json"
    if lock_path.exists():
        problems.append(f"{lock_path} exists: a holdout lock is immutable")
    if problems:
        for p in problems:
            print("REFUSED: " + p)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    frozen = {"schema": "sportreel.holdout_gt.v1", "holdout_id": hid, "members": members,
              "digest": _sha(_canon(members)), "conditions": cond}
    (out_dir / "frozen.json").write_text(json.dumps(frozen, indent=1, sort_keys=True))
    lock = {"schema": "sportreel.holdout_lock.v1", "holdout_id": hid, "gt_digest": frozen["digest"],
            "source_sha256": sorted(shas), **code_state(), "metrics": metrics, "budget_cap_usd": float(budget_cap),
            "dev_sets_checked": [str(p) for p in dev_gt] + [str(p) for p in dev_sha_files]}
    lock_path.write_text(json.dumps(lock, indent=1, sort_keys=True))
    print(f"FROZEN {hid}: {len(members)} sources, digest {frozen['digest'][:16]}, code {lock['code_sha'][:10]}")
    return 0


def verify_lock(lock_path: Path) -> int:
    lock = json.loads(lock_path.read_text())
    now = code_state()
    bad = []
    if now["thresholds_sha256"] != lock["thresholds_sha256"]:
        bad.append("sport-profile thresholds changed after the freeze")
    for p, d in lock["prompt_sources_sha256"].items():
        if now["prompt_sources_sha256"].get(p) != d:
            bad.append(f"prompt source changed after the freeze: {p}")
    for b in bad:
        print("LOCK VIOLATION: " + b)
    print("LOCK OK" if not bad else "LOCK BROKEN")
    return 1 if bad else 0


def _subset(frozen: dict, shas: set[str]) -> dict:
    return {"dataset_id": frozen["holdout_id"], "members": [m for m in frozen["members"] if m["sha256"] in shas]}


def normalised(report: dict, fps: dict[str, float]) -> dict:
    rides = report["rides"]
    n = len(rides)
    minutes = sum(r["frames"] / fps.get(r["source_sha256"], 30.0) for r in rides) / 60.0
    tol = gs.BOUNDARY_TOLERANCE_SEC
    return {"rides": n,
            "full_rate": round(sum(1 for r in rides if r.get("full")) / n, 3) if n else None,
            "ge95_rate": round(sum(1 for r in rides if r.get("ge95")) / n, 3) if n else None,
            "missing_sec_per_ride_minute": round(sum(r["missing_sec"] for r in rides) / minutes, 2) if minutes else None,
            "wrong_start_rate": round(sum(1 for r in rides if (r.get("start_error_sec") or 0) > tol) / n, 3) if n else None,
            "wrong_end_rate": round(sum(1 for r in rides if (r.get("end_error_sec") or 0) > tol) / n, 3) if n else None,
            "counts": {k: report["metrics"].get(k) for k in ("published", "published_correct", "published_wrong_identity",
                                                              "excluded_frames_selected", "split_athletes", "mixed_reels")}}


def evaluate(frozen_path: Path, lock_path: Path, diagnostics: Path, out: Path | None) -> int:
    frozen = json.loads(frozen_path.read_text())
    lock = json.loads(lock_path.read_text())
    if frozen["digest"] != lock["gt_digest"] or _sha(_canon(frozen["members"])) != frozen["digest"]:
        print("REFUSED: holdout GT digest does not match its lock")
        return 1
    manifest = gs._load(diagnostics / "publishable_reel_manifest.json")
    pred = diagnostics / "predictions.v1.json"
    predictions = gs._load(pred) if pred.exists() else None
    gt_all = _subset(frozen, set(lock["source_sha256"]))
    overall = gs.evaluate(gt_all, manifest, predictions)
    fps = {sha: v["fps"] for sha, v in gs.load_gt(gt_all).items()}
    result = {"holdout_id": frozen["holdout_id"], "gt_digest": frozen["digest"], "code_sha_locked": lock["code_sha"],
              "overall": normalised(overall, fps), "strata": {}}
    cond = frozen.get("conditions") or {}
    groups: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for sha, tags in cond.items():
        for k, v in tags.items():
            for val in (v if isinstance(v, list) else [v]):
                groups[k][str(val)].add(sha)
    for r in overall["rides"]:
        groups["athlete"][str(r["athlete_id"])].add(r["source_sha256"])
    for key, vals in groups.items():
        for val, shas in sorted(vals.items()):
            result["strata"].setdefault(key, {})[val] = normalised(gs.evaluate(_subset(frozen, shas), manifest, predictions), fps)
    verdicts = {}
    o = result["overall"]
    for name, rule in {**lock["metrics"]["success"], **lock["metrics"]["protected"]}.items():
        value = o.get(name, (o.get("counts") or {}).get(name))
        op, thr = rule
        ok = value is not None and (value >= thr if op == ">=" else value <= thr)
        verdicts[name] = {"value": value, "rule": f"{op} {thr}", "pass": ok}
    result["preregistered"] = verdicts
    result["pass"] = all(v["pass"] for v in verdicts.values())
    text = json.dumps(result, indent=1)
    if out:
        out.write_text(text)
    print(json.dumps({"overall": result["overall"], "pass": result["pass"]}, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--gt", type=Path, required=True); f.add_argument("--conditions", type=Path, required=True)
    f.add_argument("--id", required=True); f.add_argument("--out-dir", type=Path, required=True)
    f.add_argument("--dev-gt", type=Path, action="append", default=[ROOT / "evaluation/ground_truth/gtv1_frozen.json"])
    f.add_argument("--dev-sha-file", type=Path, action="append", default=[])
    f.add_argument("--budget-cap", type=float); f.add_argument("--metrics", type=Path, required=True)
    v = sub.add_parser("verify-lock"); v.add_argument("--lock", type=Path, required=True)
    e = sub.add_parser("evaluate")
    e.add_argument("--frozen", type=Path, required=True); e.add_argument("--lock", type=Path, required=True)
    e.add_argument("--diagnostics", type=Path, required=True); e.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.cmd == "freeze":
        return freeze(a.gt, a.conditions, a.id, a.out_dir, a.dev_gt, a.dev_sha_file, a.budget_cap, a.metrics)
    if a.cmd == "verify-lock":
        return verify_lock(a.lock)
    return evaluate(a.frozen, a.lock, a.diagnostics, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
