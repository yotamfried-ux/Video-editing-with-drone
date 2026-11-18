#!/usr/bin/env python3
"""Cycle 12 holdout infrastructure (scripts/holdout_qualification.py), synthetic fixtures only - NOT a holdout result.

H1  freeze refuses a holdout that contains ANY GT-v1 (development) source
H2  freeze refuses missing condition tags, missing reviewed ranges, no budget cap, no pre-registered thresholds
H3  a valid freeze writes frozen.json + lock.json (GT digest, code SHA, threshold and prompt digests, sources, cap)
H4  a lock is immutable: a second freeze into the same directory is refused
H5  verify-lock passes on unchanged code and FAILS once a sport-profile threshold is tuned after the freeze
H6  evaluate refuses a GT whose digest no longer matches its lock (a holdout edited after the freeze)
H7  evaluate reports normalised rates (FULL / >=95 % / wrong start / wrong end per ride, missing seconds per ride
    minute) overall and per stratum (athlete, every condition tag) and the pre-registered pass/fail table
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import holdout_qualification as hq  # noqa: E402

FAILS: list[str] = []
FPS = 60000 / 1001


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def member(sha, rides, reviewed=True):
    segs = [{"decision": "include", "athlete_id": a, "start_frame": s, "end_frame": e} for a, s, e in rides]
    return {"sha256": sha, "content": {"fps_num": 60000, "fps_den": 1001, "segments": segs,
                                       "reviewed_ranges": [{"start_frame": 0, "end_frame": 3000}] if reviewed else []}}


def quiet(fn, *a):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = fn(*a)
    return code, buf.getvalue()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="holdout-"))
    gtv1 = json.loads((ROOT / "evaluation/ground_truth/gtv1_frozen.json").read_text())
    dev = [ROOT / "evaluation/ground_truth/gtv1_frozen.json"]
    a, b = "a" * 64, "b" * 64
    tags = {"lighting": "midday", "distance": "near", "crowding": "solo", "camera_motion": "static", "difficulty": "easy"}
    cond = {a: dict(tags, action_types=["early_paddle"]), b: dict(tags, lighting="low_sun", difficulty="hard", action_types=["fast_start"])}
    gt = {"dataset_id": "H-test", "members": [member(a, [("P1", 0, 600)]), member(b, [("P2", 120, 900)])]}
    metrics = {"success": {"full_rate": [">=", 0.5]}, "protected": {"published_wrong_identity": ["<=", 0]}}
    files = {}
    for name, obj in (("gt", gt), ("cond", cond), ("metrics", metrics)):
        files[name] = tmp / f"{name}.json"
        files[name].write_text(json.dumps(obj))

    bad = tmp / "gt_overlap.json"
    bad.write_text(json.dumps({"members": gt["members"] + [gtv1["members"][0]]}))
    cond_b = tmp / "cond_b.json"
    cond_b.write_text(json.dumps(dict(cond, **{gtv1["members"][0]["sha256"]: tags})))
    code, out = quiet(hq.freeze, bad, cond_b, "H-x", tmp / "x", dev, [], 1.0, files["metrics"])
    check(code == 1 and "development data" in out, "H1 a holdout with a GT-v1 source is refused")

    notag = tmp / "cond_notag.json"
    notag.write_text(json.dumps({a: {"lighting": "x"}, b: tags}))
    code1, o1 = quiet(hq.freeze, files["gt"], notag, "H-y", tmp / "y", dev, [], 1.0, files["metrics"])
    unrev = tmp / "gt_unrev.json"
    unrev.write_text(json.dumps({"members": [member(a, [("P1", 0, 600)], reviewed=False)]}))
    code2, o2 = quiet(hq.freeze, unrev, files["cond"], "H-y", tmp / "y", dev, [], 1.0, files["metrics"])
    code3, o3 = quiet(hq.freeze, files["gt"], files["cond"], "H-y", tmp / "y", dev, [], None, files["metrics"])
    nomet = tmp / "metrics_empty.json"
    nomet.write_text("{}")
    code4, o4 = quiet(hq.freeze, files["gt"], files["cond"], "H-y", tmp / "y", dev, [], 1.0, nomet)
    check(code1 == code2 == code3 == code4 == 1 and "tags missing" in o1 and "reviewed range" in o2
          and "budget cap" in o3 and "pre-registered" in o4,
          "H2 missing tags / reviewed range / budget cap / thresholds are each refused")

    hdir = tmp / "H1"
    code, _ = quiet(hq.freeze, files["gt"], files["cond"], "H1", hdir, dev, [], 0.40, files["metrics"])
    lock = json.loads((hdir / "lock.json").read_text()) if (hdir / "lock.json").exists() else {}
    check(code == 0 and lock.get("gt_digest") and lock.get("thresholds_sha256") and lock.get("prompt_sources_sha256")
          and lock.get("source_sha256") == sorted([a, b]) and lock.get("budget_cap_usd") == 0.40,
          "H3 freeze writes frozen.json + lock.json (digest, code, thresholds, prompts, sources, cap)")
    code, out = quiet(hq.freeze, files["gt"], files["cond"], "H1", hdir, dev, [], 0.40, files["metrics"])
    check(code == 1 and "immutable" in out, "H4 an existing lock is never overwritten")

    code_ok, _ = quiet(hq.verify_lock, hdir / "lock.json")
    from pipeline.sport_profiles import surfing
    saved = surfing.SURFING.onset.min_motion_body_heights_per_sec
    object.__setattr__(surfing.SURFING.onset, "min_motion_body_heights_per_sec", 0.15) \
        if hasattr(surfing.SURFING.onset, "__dataclass_fields__") else None
    code_bad, out_bad = quiet(hq.verify_lock, hdir / "lock.json")
    object.__setattr__(surfing.SURFING.onset, "min_motion_body_heights_per_sec", saved)
    check(code_ok == 0 and code_bad == 1 and "thresholds changed" in out_bad,
          "H5 verify-lock passes unchanged and fails after a threshold is tuned post-freeze")

    diag = tmp / "diag"
    diag.mkdir()
    sec = lambda f: f / FPS
    rows = [{"athlete_key": "k1", "parts": [{"part_index": 1, "publishable": True, "qualification_inputs": {"events": [
                {"event_uid": "e1", "source_sha256": a, "source_frame_range_sec": [sec(0), sec(600)]}]}}]},
            {"athlete_key": "k2", "parts": [{"part_index": 1, "publishable": True, "qualification_inputs": {"events": [
                {"event_uid": "e2", "source_sha256": b, "source_frame_range_sec": [sec(300), sec(900)]}]}}]}]
    (diag / "publishable_reel_manifest.json").write_text(json.dumps({"pipeline_run_id": "r", "athletes": rows}))
    frozen = json.loads((hdir / "frozen.json").read_text())
    tampered = tmp / "tampered.json"
    frozen_t = dict(frozen, members=frozen["members"][:1])
    tampered.write_text(json.dumps(frozen_t))
    code, out = quiet(hq.evaluate, tampered, hdir / "lock.json", diag, None)
    check(code == 1 and "digest" in out, "H6 a holdout GT edited after the freeze is refused")

    res_path = tmp / "res.json"
    code, _ = quiet(hq.evaluate, hdir / "frozen.json", hdir / "lock.json", diag, res_path)
    res = json.loads(res_path.read_text()) if res_path.exists() else {}
    o = res.get("overall", {})
    st = res.get("strata", {})
    check(code == 0 and o.get("rides") == 2 and o.get("full_rate") == 0.5 and o.get("wrong_start_rate") == 0.5
          and o.get("missing_sec_per_ride_minute") and set(st) >= {"athlete", "lighting", "difficulty", "action_types"}
          and st["difficulty"]["hard"]["full_rate"] == 0.0 and st["difficulty"]["easy"]["full_rate"] == 1.0
          and res["preregistered"]["full_rate"]["pass"] is True,
          f"H7 normalised + stratified metrics and the pre-registered table ({o})")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
