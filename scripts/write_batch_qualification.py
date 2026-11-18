#!/usr/bin/env python3
"""Write `batch_qualification.json`: execution success and product success, kept apart (RC-07).

A green workflow says the pipeline ran; it does not say every athlete got a correct reel. This artifact states both:

  execution_state = SUCCESS | FAILED          (the pipeline process exit code)
  product_state   = PASS | PARTIAL | FAIL | BLOCKED

PASS needs every eligible athlete verified publishable (each part's output qualification passes) and no athlete
unaccounted for. PARTIAL: some verified, some withheld. FAIL: none verified. BLOCKED: the evidence needed to judge
the batch is missing (no manifest, unreadable manifest). The verdict is also merged into the operator's
pipeline_runs row meta (`--record`), so the app shows a partial batch as partial, never as complete.

usage: write_batch_qualification.py --manifest M --out OUT [--coverage C] [--gt-eval E] [--exit-code N] [--record]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCHEMA = "sportreel.batch_qualification.v1"


def _load(path: str | None) -> Any:
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _parts(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in row.get("parts", []) or [] if isinstance(p, dict)]


def _qualification(part: dict[str, Any]) -> dict[str, Any]:
    q = part.get("output_qualification")
    return q if isinstance(q, dict) else {}


def _verified(part: dict[str, Any]) -> bool:
    try:
        from pipeline.output_qualification import verify
    except Exception:  # noqa: BLE001 - without the verifier nothing counts as verified
        return False
    return part.get("publishable") is True and verify(_qualification(part))


def _shot_verdicts(part: dict[str, Any]) -> list[str]:
    inputs = part.get("qualification_inputs") if isinstance(part.get("qualification_inputs"), dict) else {}
    return [str((e.get("eligibility") or {}).get("verdict")) for e in inputs.get("events") or []]


_SOURCE_LIMIT_ISSUES = ("qualification:tail_after_actor_lost_to_recording_end",)


def _source_limited(part: dict[str, Any]) -> bool:
    """Withheld only because the recording ended: a recording-end note and no other blocking reason.

    A part blocked for identity, QA or anything else is REVIEW_REQUIRED even when one of its shots also ends at the
    recording end (run 43920602179 labelled five identity-withheld athletes SOURCE_LIMITED).
    """
    inputs = part.get("qualification_inputs") if isinstance(part.get("qualification_inputs"), dict) else {}
    noted = any("source_limited_recording_end" in (e.get("interval") or {}).get("notes", [])
                for e in inputs.get("events") or [])
    blocking = [str(b) for b in (_qualification(part).get("blocking") or part.get("technical_issues") or [])]
    return noted and bool(blocking) and all(b.startswith(_SOURCE_LIMIT_ISSUES) for b in blocking)


def build(manifest: Any, *, coverage: Any = None, gt_eval: Any = None, exit_code: int | None = None) -> dict[str, Any]:
    execution = "SUCCESS" if exit_code == 0 else ("FAILED" if exit_code is not None else "UNKNOWN")
    base = {
        "schema": SCHEMA,
        "pipeline_run_id": os.getenv("PIPELINE_RUN_ID") or (manifest.get("pipeline_run_id") if isinstance(manifest, dict) else None),
        "github_run_id": os.getenv("GITHUB_RUN_ID") or None,
        "commit_sha": os.getenv("SPORTREEL_COMMIT") or os.getenv("GITHUB_SHA") or None,
        "execution_state": execution,
    }
    if not isinstance(manifest, dict) or not isinstance(manifest.get("athletes"), list):
        return {**base, "product_state": "BLOCKED", "blocked_reason": "publishable manifest missing or unreadable",
                "athletes": [], "counts": {}}

    athletes: list[dict[str, Any]] = []
    counts = {"eligible_athlete_count": 0, "verified_publishable_athlete_count": 0, "quarantined_athlete_count": 0,
              "source_limited_athlete_count": 0, "hard_rejected_athlete_count": 0, "qa_failure_part_count": 0}
    sources: set[str] = set()
    critical: list[dict[str, Any]] = []
    for row in manifest["athletes"]:
        if not isinstance(row, dict) or not row.get("eligible", True):
            continue
        parts = _parts(row)
        counts["eligible_athlete_count"] += 1
        verified = bool(parts) and all(_verified(p) for p in parts)
        verdicts = [v for p in parts for v in _shot_verdicts(p)]
        for p in parts:
            sources.update(_qualification(p).get("source_shas") or [])
            if str(p.get("qa_verdict") or "").upper() != "PASS":
                counts["qa_failure_part_count"] += 1
            if not _verified(p):
                critical.append({"athlete_key": row.get("athlete_key"), "part_index": p.get("part_index"),
                                 "blocking": (_qualification(p).get("blocking") or p.get("technical_issues") or [])[:20]})
        if verified:
            state = "PUBLISHED_VERIFIED"
            counts["verified_publishable_athlete_count"] += 1
        elif verdicts and all(v == "INVALID_ACTION" for v in verdicts):
            state = "HARD_REJECTED"
            counts["hard_rejected_athlete_count"] += 1
        elif parts and all(_source_limited(p) for p in parts if not _verified(p)):
            state = "SOURCE_LIMITED"
            counts["source_limited_athlete_count"] += 1
        else:
            state = "REVIEW_REQUIRED"
            counts["quarantined_athlete_count"] += 1
        athletes.append({"athlete_key": row.get("athlete_key"), "state": state,
                         "parts": [{"part_index": p.get("part_index"), "content_sha256": p.get("content_sha256"),
                                    "content_sha256_kind": p.get("content_sha256_kind"),
                                    "proof_digest": _qualification(p).get("proof_digest"),
                                    "product_state": _qualification(p).get("product_state"),
                                    "publishable": p.get("publishable") is True} for p in parts]})

    summary = (coverage or {}).get("summary") if isinstance(coverage, dict) else None
    if isinstance(summary, dict) and summary.get("confirmed_athlete_cluster_count") is not None:
        unaccounted = int(summary.get("confirmed_athlete_cluster_count") or 0) - int(
            summary.get("covered_or_explicitly_explained_cluster_count") or 0)
        accounting = "athlete_coverage_report"
    else:
        unaccounted, accounting = None, "coverage_report_missing"
    counts["unaccounted_athlete_count"] = unaccounted

    eligible, verified_count = counts["eligible_athlete_count"], counts["verified_publishable_athlete_count"]
    if unaccounted is None:
        product = "BLOCKED"
    elif eligible and verified_count == eligible and unaccounted == 0:
        product = "PASS"
    elif verified_count:
        product = "PARTIAL"
    else:
        product = "FAIL"
    if isinstance(gt_eval, dict):
        gt = {"status": gt_eval.get("status"), "report_digest": gt_eval.get("report_digest"),
              "metrics": gt_eval.get("metrics"), "physical_rides": (gt_eval.get("physical_rides") or {}).get("summary")}
    else:
        gt = {"status": "NOT_RUN"}
    body = {**base, "product_state": product, "athlete_accounting": accounting, "counts": counts,
            "source_shas": sorted(sources), "gt_benchmark": gt, "unresolved_critical": critical, "athletes": athletes}
    body["digest"] = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--coverage")
    parser.add_argument("--gt-eval")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--record", action="store_true", help="merge the verdict into the pipeline_runs row meta")
    args = parser.parse_args()
    result = build(_load(args.manifest), coverage=_load(args.coverage), gt_eval=_load(args.gt_eval),
                   exit_code=args.exit_code)
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    c = result.get("counts") or {}
    print(f"batch qualification: execution={result['execution_state']} product={result['product_state']} "
          f"verified={c.get('verified_publishable_athlete_count')}/{c.get('eligible_athlete_count')} "
          f"review={c.get('quarantined_athlete_count')} unaccounted={c.get('unaccounted_athlete_count')}")
    if args.record:
        try:
            from integrations.run_status import mark_run
            mark_run(meta={"execution_state": result["execution_state"], "product_state": result["product_state"],
                           "batch_qualification_counts": c, "batch_qualification_digest": result.get("digest")})
        except Exception as exc:  # noqa: BLE001 - the artifact is the record; the meta is a mirror
            print(f"could not mirror the batch verdict into the run row: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
