#!/usr/bin/env python3
"""Read-only cross-artifact qualification for a SportReel pipeline diagnostics ZIP/directory.

This is an *offline evidence consistency* gate, NOT proof of visual quality, live R2
state, mobile behavior, or the real provider integration. No cloud credentials needed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED = (
    "summary.json",
    "candidate_decision_ledger.json",
    "selection_decision_audit.json",
    "draft_decision_trace.json",
    "athlete_coverage_report.json",
    "publishable_reel_manifest.json",
    "publishable_reel_gate_result.json",
    "run_quality_report.json",
)


def _read(source: Path, name: str) -> Any:
    if source.is_file():
        with zipfile.ZipFile(source) as z:
            # Avoid traversal and archives with prefixed directory names by
            # intentionally selecting exact known member names only.
            return json.loads(z.read(name).decode("utf-8"))
    return json.loads((source / name).read_text(encoding="utf-8"))


def _members(source: Path) -> set[str]:
    if source.is_file():
        with zipfile.ZipFile(source) as z:
            return set(z.namelist())
    return {str(p.relative_to(source)).replace(os.sep, "/") for p in source.rglob("*") if p.is_file()}


def evaluate(source: Path, *, run_id: str = "unknown") -> dict[str, Any]:
    """Return a report even if evidence is missing; no mutation or external I/O."""
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, details: str, *, observed: Any = None) -> None:
        checks.append({"id": name, "status": "PASS" if passed else "FAIL", "details": details,
                       "observed": observed})

    files = _members(source)
    missing = sorted(set(REQUIRED) - files)
    check("REQUIRED_ARTIFACTS", not missing, "Required diagnostic JSON files are present", observed=missing)
    if missing:
        return _report(run_id, checks, note="Cannot inspect missing diagnostic evidence")
    try:
        summary, ledger, audit, trace, coverage, manifest, gate, quality = [
            _read(source, path) for path in REQUIRED
        ]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        check("PARSE_ARTIFACTS", False, f"Invalid diagnostic JSON: {type(exc).__name__}")
        return _report(run_id, checks)

    check("ARTIFACT_SCHEMAS", all(isinstance(x, dict) for x in
                                  (summary, ledger, audit, trace, coverage, manifest, gate, quality)),
          "Every required JSON document must be an object")
    if any(not isinstance(x, dict) for x in (summary, ledger, audit, trace, coverage, manifest, gate, quality)):
        return _report(run_id, checks)

    sidecars = [n for n in files if re.fullmatch(r"sidecars/[^/]+\.perception\.json", n)]
    expected_sidecars = summary.get("sidecar_count")
    valid_count = isinstance(expected_sidecars, int) and not isinstance(expected_sidecars, bool)
    check("PERCEPTION_SIDECAR_INVENTORY", valid_count and expected_sidecars > 0 and
          len(sidecars) == expected_sidecars and len(summary.get("sidecars") or []) == expected_sidecars,
          "Perception sidecar files and summary must match; does not prove tracker accuracy",
          observed={"listed": expected_sidecars, "files": len(sidecars)})
    check("PERCEPTION_SCHEMA_DIAGNOSTICS", not (quality.get("sidecar_schema_errors") or []),
          "Production quality report must report no sidecar schema errors",
          observed=len(quality.get("sidecar_schema_errors") or []))

    candidates = ledger.get("candidates") or []
    selected = sum(1 for row in candidates if row.get("selected") is True)
    discarded = sum(1 for row in candidates if row.get("discarded") is True)
    check("CANDIDATE_LEDGER_CONSISTENCY", bool(candidates) and
          len(candidates) == ledger.get("candidate_count") == selected + discarded and
          selected == ledger.get("selected_count") and discarded == ledger.get("discarded_count") and
          not any(bool(row.get("selected")) == bool(row.get("discarded")) for row in candidates),
          "Every candidate must have exactly one selected/discarded decision",
          observed={"candidates": len(candidates), "selected": selected, "discarded": discarded})

    audit_candidates = audit.get("candidates") or []
    a_summary = audit.get("summary") or {}
    ambiguous = sum(1 for row in audit_candidates if row.get("discarded") and
                    row.get("discard_cause_detailed") == "selected_by_selector_not_emitted_as_draft")
    check("UNEXPLAINED_SELECTOR_DROP", ambiguous == 0,
          "Selector-selected candidate cannot disappear without a downstream explicit outcome",
          observed={"unexplained": ambiguous})
    check("SELECTION_AUDIT_CONSISTENCY", len(audit_candidates) == len(candidates) == a_summary.get("candidate_count") and
          a_summary.get("selected_count") == selected and a_summary.get("discarded_count") == discarded,
          "Decision audit and candidate ledger must have matching counts",
          observed={"audit": len(audit_candidates), "ledger": len(candidates)})

    drafts = trace.get("drafts") or []
    draft_names = [str(d.get("draft_name") or "") for d in drafts]
    check("DRAFT_TRACE_CONSISTENCY", bool(drafts) and len(drafts) == trace.get("draft_count") and
          len(set(draft_names)) == len(draft_names) and all(draft_names),
          "Every draft must have a unique durable trace", observed={"drafts": len(drafts)})

    athletes = manifest.get("athletes") or []
    parts = [p for row in athletes if isinstance(row, dict) for p in row.get("parts", []) or [] if isinstance(p, dict)]
    mapped_names = [str(p.get("review_draft_name")) for p in parts if p.get("uploaded_to_review")]
    missing_drafts = sorted(set(draft_names) - set(mapped_names))
    extras = sorted(set(mapped_names) - set(draft_names))
    check("REVIEW_MANIFEST_RECONCILIATION", not missing_drafts and not extras and
          len(draft_names) == len(mapped_names) and len(set(mapped_names)) == len(mapped_names),
          "Every REVIEW draft must map bijectively to exactly one manifest part",
          observed={"drafts": len(draft_names), "parts": len(parts), "uploaded_manifest_parts": len(mapped_names),
                    "missing_count": len(missing_drafts), "extra_count": len(extras),
                    "missing_names": missing_drafts})

    bad_qa = [p.get("review_draft_name") or p.get("local_file_name") for p in parts
              if not (p.get("qa_evidence_recorded") is True and
                      p.get("qa_verdict") in ("PASS", "FAIL") and
                      p.get("qa_passed") is (p.get("qa_verdict") == "PASS"))]
    check("FINAL_QA_EVIDENCE", bool(parts) and not bad_qa,
          "Every final manifest part must carry explicit final QA verdict; FAIL is valid evidence but not publishable",
          observed={"parts": len(parts), "missing_or_invalid": len(bad_qa)})

    publishable = [p for p in parts if p.get("publishable") is True]
    unsafe = [p.get("review_draft_name") or p.get("local_file_name") for p in publishable
              if p.get("qa_verdict") != "PASS" or p.get("qa_evidence_recorded") is not True]
    check("PUBLISHABILITY_FAIL_CLOSED", not unsafe,
          "No publishable part may lack explicit QA PASS evidence", observed={"unsafe_count": len(unsafe)})

    c_summary = coverage.get("summary") or {}
    covered = c_summary.get("athlete_accountability_rate")
    gaps = c_summary.get("coverage_gap_cluster_count")
    check("ATHLETE_ACCOUNTABILITY", covered == 1.0 and gaps == 0,
          "All detected eligible clusters must have a supported output or explicit no-output outcome",
          observed={"rate": covered, "unresolved_clusters": gaps})

    subject_violations = quality.get("mixed_subject_likely_windows") or []
    check("PRIMARY_SUBJECT_GATE", not subject_violations,
          "No final draft may retain a blocking primary-subject policy violation",
          observed={"violations": len(subject_violations)})
    check("BUSINESS_GATE", gate.get("passed") is True and not gate.get("errors"),
          "Authoritative publishability gate must pass, independently of upload count",
          observed={"passed": gate.get("passed"), "error_count": len(gate.get("errors") or [])})
    return _report(run_id, checks, note="Offline evidence only: does not prove rendered-video visuals or live provider boundaries")


def _report(run_id: str, checks: list[dict[str, Any]], *, note: str = "") -> dict[str, Any]:
    failures = [c["id"] for c in checks if c["status"] == "FAIL"]
    return {"schema_version": "sportreel.pipeline_offline_qualification.v1",
            "run_id": run_id, "generated_at": datetime.now(timezone.utc).isoformat(),
            "offline_status": "FAIL" if failures else "PASS", "failed_checks": failures,
            "system_e2e_status": "NOT_TESTED", "checks": checks,
            "scope": "offline-artifact-consistency", "note": note,
            "unverified": ["real source-to-output visual correspondence", "LLM/provider boundary reliability",
                           "production R2/Supabase current state", "Android/Operator live journey"]}


def as_markdown(report: dict[str, Any]) -> str:
    head = ["# SportReel pipeline offline qualification", "",
            f"Run: `{report['run_id']}` | Offline: **{report['offline_status']}** | System E2E: **{report['system_e2e_status']}**", "",
            "| Check | Result | Observation |", "|---|---|---|"]
    for check in report["checks"]:
        observation = json.dumps(check.get("observed"), ensure_ascii=False)
        if len(observation) > 210:
            observation = observation[:207] + "..."
        head.append(f"| `{check['id']}` | {check['status']} | {observation.replace('|', '/')} |")
    head.extend(["", report.get("note", ""), "", "**Unverified (not implied by offline PASS):** " +
                 "; ".join(report["unverified"]) + ".", ""])
    return "\n".join(head)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Read-only GitHub diagnostics ZIP or extracted directory")
    parser.add_argument("--run-id", default="unknown")
    parser.add_argument("--out", type=Path, default=Path("qualification-report.json"))
    parser.add_argument("--markdown", type=Path, default=Path("qualification-report.md"))
    args = parser.parse_args()
    if not args.source.exists() or not (args.source.is_dir() or zipfile.is_zipfile(args.source)):
        parser.error("source must be an existing directory or valid ZIP")
    result = evaluate(args.source, run_id=args.run_id)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(as_markdown(result), encoding="utf-8")
    print(f"Offline qualification: {result['offline_status']} | failed checks: {','.join(result['failed_checks']) or 'none'}")
    return 1 if result["offline_status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())