#!/usr/bin/env python3
"""Cross-source athlete identity: method comparison against the frozen Ground Truth (EVALUATION ONLY).

Question: which decision rule merges the same athlete across clips with zero confirmed false merges and few
false splits? Unsure pairs must land in REVIEW, never in an automatic release.

Data (nothing here is read by inference):
  * appearances = (source sha256, pipeline actor track) of every selected event of one run's diagnostics, labelled
    with the GT athlete whose ride covers >= 30 % of the event window (events without exactly one athlete are
    skipped). LABEL-NOISE LIMIT: the pipeline's actor track is not frame-level GT (PQ-19/PQ-04).
  * pairs = appearances of different sources. Split by ATHLETE, fixed before any result: athletes sorted by
    sha256(athlete_id); the first HOLDOUT_ATHLETES are the holdout. Prompts/thresholds are tuned on dev only;
    cross-split pairs are never evaluated.
  * media: crops are cut from the compressed processed proxies INSIDE this process (R2 read-only) and sent to
    Gemini as inline bytes. No image, crop or video is written to disk outside the temp dir, logged, or uploaded.
    The result file holds verdicts and counts only (the repository is public).

Methods: M0 current production verifier prompt (one 4-crop sheet per clip, permissive); M1 pairwise 6-crop sheets
with explicit matching / contradicting features; M2 = M1 in both image orders + consensus rule (MATCH only if both
orders agree with >= 2 specific features and no contradiction; NO_MATCH only if both orders say so; else REVIEW);
M4 hand-crafted colour histogram (no model, dev-calibrated threshold).

usage: identity_pair_experiment.py --diagnostics DIR --out FILE --phase dev|holdout [--budget-usd 0.9] [--dry-run]
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gt_scorecard as sc  # noqa: E402

MODEL = "gemini-2.5-flash"
PRICE_IN_PER_M, PRICE_OUT_PER_M = 0.30, 2.50      # USD / 1M tokens (estimate; real usage tokens are recorded)
HOLDOUT_ATHLETES = 4
CROPS_M0, CROPS_M1 = 4, 6
SEED = 20261116
NEG_CAP = {"dev": 60, "holdout": 40}
LABEL_SHARE = 0.3

M1_PROMPT = """\
Two images follow. Each is a contact sheet of crops of ONE tracked person, cut from a drone video of a different clip.
Decide whether the two people are the SAME athlete. Aerial footage: faces are not usable.
Compare only what is actually visible: board colour/shape/stripes/logos, wetsuit or rash-guard/top/shorts colours and
patterns, hair, body build, helmet/hat, leash, any numbers.
Generic traits shared by many surfers (dark shorts, light top, a longboard, a pink board of common shape) are NOT
enough to say MATCH. Look for contradictions as hard as for agreement.
Return ONLY JSON:
{"verdict": "MATCH|NO_MATCH|UNCERTAIN",
 "matching_features": ["specific feature visible in both"],
 "contradicting_features": ["feature that differs"],
 "generic_only": true|false}
Rules: MATCH needs at least two independent specific matching features and no contradiction. A clear contradiction
(different board colour or pattern, different top/shorts colour) is NO_MATCH. Otherwise UNCERTAIN."""


# ------------------------------------------------------------------ pure logic (unit-tested)
def parse_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        value = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def m0_decision(parsed: dict[str, Any] | None) -> str:
    """Production semantics: only an explicit boolean same_person confirms; anything else is not a merge."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("same_person"), bool):
        return "REVIEW"
    return "MATCH" if parsed["same_person"] else "NO_MATCH"


def _features(parsed: dict[str, Any] | None, key: str) -> list[str]:
    value = (parsed or {}).get(key)
    return [str(v) for v in value if str(v).strip()] if isinstance(value, list) else []


def single_verdict(parsed: dict[str, Any] | None) -> str:
    """M1 verdict with its own self-consistency rules (a MATCH that cites a contradiction or < 2 features is UNCERTAIN)."""
    if not isinstance(parsed, dict):
        return "REVIEW"
    verdict = str(parsed.get("verdict", "")).upper()
    match, contra = _features(parsed, "matching_features"), _features(parsed, "contradicting_features")
    if verdict == "MATCH":
        return "MATCH" if len(match) >= 2 and not contra and parsed.get("generic_only") is not True else "REVIEW"
    if verdict == "NO_MATCH":
        return "NO_MATCH" if contra else "REVIEW"
    return "REVIEW"


def consensus(forward: dict[str, Any] | None, backward: dict[str, Any] | None) -> str:
    """M2: automatic MATCH / NO_MATCH only when BOTH image orders agree; every disagreement or doubt is REVIEW."""
    a, b = single_verdict(forward), single_verdict(backward)
    if a == b == "MATCH":
        return "MATCH"
    if a == b == "NO_MATCH":
        return "NO_MATCH"
    return "REVIEW"


def score_pairs(rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    """rows: {same: bool, hard: bool, <method>: MATCH|NO_MATCH|REVIEW|None}. None = not evaluated (budget)."""
    out: dict[str, Any] = {}
    for subset, pick in (("all", lambda r: True), ("hard_negatives", lambda r: (not r["same"]) and r.get("hard"))):
        sel = [r for r in rows if pick(r) and r.get(method) is not None]
        pos = [r for r in sel if r["same"]]
        neg = [r for r in sel if not r["same"]]
        fm = sum(1 for r in neg if r[method] == "MATCH")
        fs = sum(1 for r in pos if r[method] == "NO_MATCH")
        out[subset] = {
            "pairs": len(sel), "positives": len(pos), "negatives": len(neg),
            "false_merges": fm, "false_splits": fs,
            "true_merges_auto": sum(1 for r in pos if r[method] == "MATCH"),
            "true_splits_auto": sum(1 for r in neg if r[method] == "NO_MATCH"),
            "review_positive": sum(1 for r in pos if r[method] == "REVIEW"),
            "review_negative": sum(1 for r in neg if r[method] == "REVIEW"),
            "false_merge_rate_upper95": wilson_upper(fm, len(neg)),
            "false_split_rate_upper95": wilson_upper(fs, len(pos)),
        }
    return out


def wilson_upper(k: int, n: int, z: float = 1.96) -> float | None:
    if n <= 0:
        return None
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return round(min(1.0, (centre + margin) / (1 + z * z / n)), 3)


def athlete_split(athlete_ids: list[str]) -> tuple[set[str], set[str]]:
    """Fixed rule, independent of any result: the first HOLDOUT_ATHLETES by sha256(id) are the holdout."""
    ordered = sorted(set(athlete_ids), key=lambda a: hashlib.sha256(a.encode()).hexdigest())
    holdout = set(ordered[:HOLDOUT_ATHLETES])
    return set(ordered) - holdout, holdout


def build_appearances(gt: dict[str, Any], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    truth = sc.load_gt(gt)
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for arow in manifest.get("athletes") or []:
        for part in arow.get("parts") or []:
            for ev in ((part.get("qualification_inputs") or {}).get("events")) or []:
                sha = ev.get("source_sha256")
                uid = str(ev.get("actor_track_uid") or "")
                rng = (ev.get("interval") or {}).get("rendered_window") or ev.get("source_frame_range_sec")
                if sha not in truth or "#" not in uid or not rng or rng[1] <= rng[0]:
                    continue
                fps = truth[sha]["fps"]
                a, b = int(round(rng[0] * fps)), int(round(rng[1] * fps))
                owners = {r["athlete_id"] for r in truth[sha]["rides"]
                          if sc._overlap(a, b, r["start_frame"], r["end_frame"]) >= LABEL_SHARE * max(1, b - a)}
                if len(owners) != 1:
                    continue                    # unlabeled or two athletes: not a clean appearance
                track = uid.rsplit("#", 1)[1]
                seen.setdefault((sha, track), {"source_sha256": sha, "track_id": track, "athlete_id": next(iter(owners)),
                                              "window_sec": [float(rng[0]), float(rng[1])]})
    return sorted(seen.values(), key=lambda x: (x["source_sha256"], x["track_id"]))


def make_pairs(apps: list[dict[str, Any]], athletes: set[str], phase: str, hard_rank: dict[tuple[int, int], float]
               ) -> list[dict[str, Any]]:
    """All same-athlete cross-source pairs + negatives: the hardest 60 % (smallest colour distance) and random rest."""
    idx = [i for i, a in enumerate(apps) if a["athlete_id"] in athletes]
    pos, neg = [], []
    for x, i in enumerate(idx):
        for j in idx[x + 1:]:
            if apps[i]["source_sha256"] == apps[j]["source_sha256"]:
                continue
            (pos if apps[i]["athlete_id"] == apps[j]["athlete_id"] else neg).append((i, j))
    cap = NEG_CAP[phase]
    neg.sort(key=lambda p: hard_rank.get(p, 0.0))
    hard_n = int(cap * 0.6)
    chosen = neg[:hard_n]
    rest = neg[hard_n:]
    random.Random(SEED).shuffle(rest)
    chosen += rest[:cap - len(chosen)]
    hard = set(neg[:max(1, len(neg) // 3)])
    return [{"i": i, "j": j, "same": True, "hard": False} for i, j in pos] + \
           [{"i": i, "j": j, "same": False, "hard": (i, j) in hard} for i, j in chosen]


# ------------------------------------------------------------------ media (never leaves this process)
def _production_prompt() -> str:
    tree = ast.parse((ROOT / "pipeline" / "stages" / "identity.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_VERIFY_PROMPT":
            return ast.literal_eval(node.value)
    raise RuntimeError("_VERIFY_PROMPT not found")


def _sheet(images: list[Any], cols: int, cell: int = 256) -> bytes:
    from PIL import Image
    rows = (len(images) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * cell, rows * cell), (0, 0, 0))
    for k, img in enumerate(images):
        img = img.copy()
        img.thumbnail((cell, cell))
        canvas.paste(img, ((k % cols) * cell + (cell - img.width) // 2, (k // cols) * cell + (cell - img.height) // 2))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _frame(video: str, t: float, tmp: str):
    from PIL import Image
    out = os.path.join(tmp, "f.jpg")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", "-q:v", "2", out],
                   check=True, timeout=120)
    return Image.open(out).convert("RGB")


def _pick(dets: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    dets = sorted(dets, key=lambda d: d["time_sec"])
    if len(dets) <= n:
        return dets
    return [dets[round(k * (len(dets) - 1) / (n - 1))] for k in range(n)]


def appearance_crops(app: dict[str, Any], sidecar: dict[str, Any], video: str, tmp: str, n: int) -> list[Any]:
    a, b = app["window_sec"]
    dets = [d for d in sidecar.get("detections") or []
            if str(d.get("track_id")) == app["track_id"] and a <= float(d["time_sec"]) <= b]
    crops = []
    for d in _pick(dets, n):
        frame = _frame(video, float(d["time_sec"]), tmp)
        sx, sy = frame.width / float(d["frame_width"]), frame.height / float(d["frame_height"])
        x0, y0, x1, y1 = d["bbox_xyxy"]
        w, h = x1 - x0, y1 - y0
        pad = 0.45                                        # context: board and water line stay in the crop
        box = (max(0, (x0 - pad * w) * sx), max(0, (y0 - pad * h) * sy),
               min(frame.width, (x1 + pad * w) * sx), min(frame.height, (y1 + pad * h) * sy))
        crops.append(frame.crop(tuple(int(v) for v in box)))
    return crops


def color_signature(crops: list[Any]):
    import numpy as np
    sigs = []
    for im in crops:
        hsv = np.asarray(im.resize((48, 48)).convert("HSV"), dtype=np.uint8)
        hist, _, _ = np.histogram2d(hsv[..., 0].ravel(), hsv[..., 1].ravel(), bins=(16, 8), range=((0, 256), (0, 256)))
        sigs.append(hist.ravel() / max(1.0, hist.sum()))
    return sigs


def color_distance(sa, sb) -> float:
    import numpy as np
    return float(min(1 - np.sum(np.sqrt(x * y)) for x in sa for y in sb))      # min Bhattacharyya distance


# ------------------------------------------------------------------ Gemini
class Budget:
    def __init__(self, cap: float) -> None:
        self.cap, self.spent, self.calls, self.tokens_in, self.tokens_out = cap, 0.0, 0, 0, 0

    def can(self) -> bool:
        return self.spent < self.cap

    def add(self, usage: Any) -> None:
        tin = int(getattr(usage, "prompt_token_count", 0) or 0)
        tout = int(getattr(usage, "candidates_token_count", 0) or 0) + int(getattr(usage, "thoughts_token_count", 0) or 0)
        self.calls += 1
        self.tokens_in += tin
        self.tokens_out += tout
        self.spent += tin * PRICE_IN_PER_M / 1e6 + tout * PRICE_OUT_PER_M / 1e6


def ask(client: Any, types: Any, budget: Budget, prompt: str, images: list[bytes]) -> dict[str, Any] | None:
    if not budget.can():
        return None
    parts: list[Any] = []
    for k, data in enumerate(images):
        parts += [f"[Image {k}]:", types.Part.from_bytes(data=data, mime_type="image/jpeg")]
    parts.append(prompt)
    response = client.models.generate_content(
        model=MODEL, contents=parts,
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"))
    budget.add(getattr(response, "usage_metadata", None))
    return parse_json(getattr(response, "text", "") or "")


# ------------------------------------------------------------------ run
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--phase", choices=["dev", "holdout"], required=True)
    ap.add_argument("--budget-usd", type=float, default=0.9)
    ap.add_argument("--m4-threshold", type=float, help="holdout: threshold frozen from the dev run (never fit on holdout)")
    ap.add_argument("--dry-run", action="store_true", help="appearances, split and pair counts only; no media, no model")
    args = ap.parse_args(argv)

    gt = json.loads(sc.DEFAULT_GT.read_text(encoding="utf-8"))
    manifest = json.loads((args.diagnostics / "publishable_reel_manifest.json").read_text(encoding="utf-8"))
    apps = build_appearances(gt, manifest)
    dev_ath, hold_ath = athlete_split([a["athlete_id"] for a in apps])
    athletes = dev_ath if args.phase == "dev" else hold_ath
    print(f"appearances={len(apps)} athletes dev={len(dev_ath)} holdout={len(hold_ath)} phase={args.phase}")

    report: dict[str, Any] = {"schema": "sportreel.identity_pair_experiment.v1", "phase": args.phase, "model": MODEL,
                              "holdout_rule": f"first {HOLDOUT_ATHLETES} athlete ids by sha256", "media_in_result": False,
                              "appearances": [{k: v for k, v in a.items() if k != "window_sec"} | {"in_phase": a["athlete_id"] in athletes}
                                              for a in apps]}
    if args.dry_run:
        pairs = make_pairs(apps, athletes, args.phase, {})
        print(f"pairs={len(pairs)} positives={sum(p['same'] for p in pairs)} negatives={sum(not p['same'] for p in pairs)}")
        return 0

    from google import genai
    from google.genai import types
    sys.path.insert(0, str(ROOT))
    from pipeline.r2_batch_restore import processed_key_for
    from integrations import r2_storage
    import urllib.parse
    import urllib.request

    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    q = urllib.parse.urlencode({"batch_id": f"eq.{os.environ['BATCH_ID']}", "removed_at": "is.null", "superseded_at": "is.null",
                                "select": "storage_key,content_sha256"})
    req = urllib.request.Request(f"{base}/rest/v1/source_uploads?{q}", headers={"apikey": key, "Authorization": f"Bearer {key}"})
    key_of = {r["content_sha256"]: r["storage_key"] for r in json.loads(urllib.request.urlopen(req, timeout=30).read())}

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    budget = Budget(args.budget_usd)
    sidecars = {}
    for f in (args.diagnostics / "sidecars").glob("*.perception.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        sidecars[d.get("source_sha256")] = d
    prod_prompt = _production_prompt()

    with tempfile.TemporaryDirectory(prefix="idexp-") as tmp:
        media: dict[int, dict[str, Any]] = {}
        need = sorted({i for i, a in enumerate(apps) if a["athlete_id"] in athletes})
        videos: dict[str, str] = {}
        for i in need:
            a = apps[i]
            sha = a["source_sha256"]
            if sha not in videos:
                if sha not in key_of or sha not in sidecars:
                    continue
                dest = os.path.join(tmp, f"{sha[:12]}.mp4")
                r2_storage.download_object(processed_key_for(key_of[sha]), dest)
                videos[sha] = dest
            crops = appearance_crops(a, sidecars[sha], videos[sha], tmp, CROPS_M1)
            if len(crops) >= 3:
                media[i] = {"sheet6": _sheet(crops, 3), "sheet4": _sheet(crops[:: max(1, len(crops) // CROPS_M0)][:CROPS_M0], 2),
                            "sig": color_signature(crops), "crops": len(crops)}
        for i, m in media.items():
            report["appearances"][i]["crops"] = m["crops"]
        usable = {i: apps[i] for i in media}
        sub = [a for i, a in enumerate(apps) if i in usable]
        remap = {i: k for k, i in enumerate(sorted(usable))}
        hard_rank = {(remap[i], remap[j]): color_distance(media[i]["sig"], media[j]["sig"])
                     for i in usable for j in usable if i < j and apps[i]["source_sha256"] != apps[j]["source_sha256"]}
        pairs = make_pairs(sub, athletes, args.phase, hard_rank)
        inv = {k: i for i, k in remap.items()}
        rows = []
        for p in pairs:
            i, j = inv[p["i"]], inv[p["j"]]
            row = dict(p, a=apps[i]["source_sha256"][:12] + "#" + apps[i]["track_id"],
                       b=apps[j]["source_sha256"][:12] + "#" + apps[j]["track_id"],
                       color_distance=round(hard_rank[(p["i"], p["j"])], 4))
            r0 = ask(client, types, budget, prod_prompt, [media[i]["sheet4"], media[j]["sheet4"]])
            row["M0"] = m0_decision(r0) if r0 is not None else None
            f = ask(client, types, budget, M1_PROMPT, [media[i]["sheet6"], media[j]["sheet6"]])
            row["M1"] = single_verdict(f) if f is not None else None
            bwd = ask(client, types, budget, M1_PROMPT, [media[j]["sheet6"], media[i]["sheet6"]])
            row["M2"] = consensus(f, bwd) if f is not None and bwd is not None else None
            row["M1_features"] = {"matching": _features(f, "matching_features")[:4], "contradicting": _features(f, "contradicting_features")[:4]}
            rows.append(row)
        report["pairs"] = rows
    dists = sorted(r["color_distance"] for r in rows if r["same"])
    if args.phase == "dev":
        thr = dists[int(0.9 * (len(dists) - 1))] if dists else None         # M4: accept 90 % of dev positives
    else:
        thr = args.m4_threshold                                              # frozen from dev; None => M4 not scored
    report["M4_threshold"] = thr
    for r in rows:
        r["M4"] = None if thr is None else ("MATCH" if r["color_distance"] <= thr else "NO_MATCH")
    report["metrics"] = {m: score_pairs(rows, m) for m in ("M0", "M1", "M2", "M4")}
    report["cost"] = {"model": MODEL, "calls": budget.calls, "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out,
                      "estimated_usd": round(budget.spent, 4), "cap_usd": args.budget_usd,
                      "pairs_not_evaluated": sum(1 for r in rows if r.get("M2") is None)}
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"cost": report["cost"], "metrics": report["metrics"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
