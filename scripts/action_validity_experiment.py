#!/usr/bin/env python3
"""EXP-14-002 harness: the PRODUCTION observer (pipeline.action_validity_runtime.observe_event) on real R2 sources.

Evaluation plane. Jobs come from a frozen run's diagnostics (every selected final window with its bound track) plus
explicit controls (--extra "SUFFIX:start:end:track;..."); no GT is read here (scoring is a separate step,
scripts/score_action_validity_experiment.py). Media: read-only R2 GETs into the job temp dir. Output: JSON only - no
image, crop or video is written outside the temp dir (public repository).

  --dry-run   build every grid exactly as production would and run the identity / coverage checks, NO model call
  (paid)      the production default_ask (integrations.gemini: budget-checked, cost-recorded); the run stops before a
              job once the recorded spend reaches --budget-usd minus one job's worst case

usage: action_validity_experiment.py --diagnostics DIR --out FILE [--dry-run] [--budget-usd 0.40] [--extra ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

JOB_WORST_CASE_USD = 0.03          # 2 passes x one 16-crop grid each, gemini-2.5-flash, generous


def _idx(name: str) -> str:
    m = re.search(r"_(\d{4})_D", name or "")
    return m.group(1) if m else name


def build_jobs(diag: Path, extra: str) -> list[dict]:
    pred = json.loads((diag / "predictions.v1.json").read_text())
    led = {c["candidate_id"]: c for c in json.loads((diag / "candidate_decision_ledger.json").read_text())["candidates"]}
    jobs = []
    for src in pred["sources"]:
        for e in src["events"]:
            if e["decision"] != "selected" or not e.get("outputs"):
                continue
            fw = led[e["candidate_id"]]["final_source_window"]
            jobs.append({"kind": "selected_final_window", "source": src["source_video"], "sha": src["source_sha256"],
                         "window": [round(fw["start"], 3), round(fw["end"], 3)], "track": str(e["outputs"][0]["track_id"])})
    for spec in [s for s in (extra or "").split(";") if s.strip()]:
        suffix, s0, s1, track = spec.split(":")
        src = next(s for s in pred["sources"] if s["source_video"].endswith(suffix))
        jobs.append({"kind": "control", "source": src["source_video"], "sha": src["source_sha256"],
                     "window": [float(s0), float(s1)], "track": track})
    return jobs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostics", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--budget-usd", type=float, default=0.40)
    ap.add_argument("--extra", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    jobs = build_jobs(a.diagnostics, a.extra)
    print(f"jobs={len(jobs)} dry_run={a.dry_run} budget={a.budget_usd}")

    tmp_root = tempfile.mkdtemp(prefix="avexp-")
    os.environ["TMP_DIR"] = tmp_root
    os.makedirs(os.path.join(tmp_root, "pipeline-debug"), exist_ok=True)
    os.environ["SPORTREEL_LLM_BUDGET_USD"] = str(a.budget_usd)        # hard cap enforced by integrations.qualification
    os.environ["SPORTREEL_LLM_DOWNSTREAM_RESERVE_USD"] = "0"
    from pipeline import action_validity_runtime as avr
    from pipeline.perception import runtime as rt
    from integrations import llm_cost, r2_storage
    from pipeline.r2_batch_restore import processed_key_for
    import urllib.parse
    import urllib.request

    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    q = urllib.parse.urlencode({"batch_id": f"eq.{os.environ['BATCH_ID']}", "removed_at": "is.null",
                                "superseded_at": "is.null", "select": "storage_key,content_sha256"})
    req = urllib.request.Request(f"{base}/rest/v1/source_uploads?{q}", headers={"apikey": key, "Authorization": f"Bearer {key}"})
    key_of = {r["content_sha256"]: r["storage_key"] for r in json.loads(urllib.request.urlopen(req, timeout=30).read())}
    sidecars = {}
    for f in (a.diagnostics / "sidecars").glob("*.perception.json"):
        d = json.loads(f.read_text())
        sidecars[d["source_sha256"]] = (f, d)

    def spent() -> float:
        return round(sum(float(c.get("cost_usd") or 0) for c in llm_cost.snapshot()), 6)

    grids_seen: list[dict] = []

    def dry_ask(image: bytes, prompt: str) -> str:
        grids_seen.append({"bytes": len(image), "sha256": hashlib.sha256(image).hexdigest()[:16],
                           "crops": len(re.search(r"\(([\d., ]+)\)", prompt).group(1).split(","))})
        return ""                                                   # no model: verdict stays UNCERTAIN by design

    rows, stopped = [], None
    videos: dict[str, str] = {}
    for job in jobs:
        if not a.dry_run and spent() + JOB_WORST_CASE_USD > a.budget_usd:
            stopped = f"budget: spent {spent()} + worst case {JOB_WORST_CASE_USD} > cap {a.budget_usd}"
            break
        row = {**job, "index": _idx(job["source"])}
        sha = job["sha"]
        try:
            if sha not in videos:
                name = key_of[sha].rsplit("/", 1)[-1]
                found = next((c for c in ("raw/" + name, key_of[sha], processed_key_for(key_of[sha]), "processed/" + name)
                              if r2_storage._head(c) is not None), None)
                if found is None:
                    rows.append(dict(row, skip="media_unavailable"))
                    continue
                dest = os.path.join(tmp_root, f"{sha[:12]}.mp4")
                r2_storage.download_object(found, dest)                 # read-only GET
                videos[sha] = dest
            side_path, payload = sidecars[sha]
            dets = rt._detections_from_payload(videos[sha], payload)
            event = {"start": job["window"][0], "end": job["window"][1], "target_track_id": job["track"],
                     "sport": "surfing", "event_type": "wave_catch"}
            grids_seen.clear()
            t0 = time.time()
            before = spent()
            result = avr.observe_event(event, videos[sha], dets, ask=dry_ask if a.dry_run else None)
            row.update({"verdict": result.get("verdict"), "basis": result.get("basis"),
                        "passes": result.get("passes"), "checks": result.get("checks"),
                        "sample_plan": result.get("sample_plan"), "grids": list(grids_seen) if a.dry_run else None,
                        "cost_usd": round(spent() - before, 6), "seconds": round(time.time() - t0, 1)})
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        rows.append(row)
        print(row["index"], job["kind"], job["window"], row.get("verdict"), row.get("basis"), row.get("cost_usd"), row.get("error", ""))
    out = {"schema": "sportreel.action_validity_experiment.v1", "experiment": "EXP-14-002",
           "executed_code_sha": os.getenv("GITHUB_SHA"), "diagnostics_run": a.diagnostics.name,
           "dry_run": a.dry_run, "budget_usd": a.budget_usd, "spent_usd": spent(), "stopped": stopped,
           "model": avr.MODEL, "prompt_version": __import__("pipeline.action_validity", fromlist=["x"]).PROMPT_VERSION,
           "llm_calls": len(llm_cost.snapshot()), "rows": rows}
    a.out.write_text(json.dumps(out, indent=1))
    print(f"spent={out['spent_usd']} calls={out['llm_calls']} stopped={stopped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
