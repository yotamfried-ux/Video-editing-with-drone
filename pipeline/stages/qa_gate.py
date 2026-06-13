"""
pipeline/stages/qa_gate.py — reel QA gate decision + reporting.

Extracted from orchestrator.py (the cohesive, independently-testable slice). The
re-edit loop (_qa_gate / _apply_qa_fixes) stays in the orchestrator because it is
tightly coupled to compilation; this module holds the pure decision + the printer.
"""

from pathlib import Path


def qa_blocking(qa: dict) -> bool:
    """A reel blocks on QA only for critical content defects — the class of
    problem the re-edit loop can actually fix by dropping/adjusting clips.

    Note: verdict 'UNKNOWN' (QA errored) is non-blocking, same as 'PASS'."""
    if qa.get("verdict") != "FAIL":
        return False
    return any(str(d.get("severity", "")).lower() == "critical"
               for d in qa.get("defects", []))


def print_qa_result(reel: str, qa: dict) -> None:
    verdict = qa.get("verdict", "PASS")
    score   = qa.get("engagement_score", "?")
    overall = qa.get("overall", "")
    name    = Path(reel).name
    if verdict == "FAIL":
        tech_issues = qa.get("technical", {}).get("issues", [])
        weak = {k: v for k, v in qa.get("content", {}).items()
                if isinstance(v, (int, float)) and v < 6}
        detail = []
        if tech_issues:
            detail.append(f"technical: {tech_issues}")
        if weak:
            detail.append(f"weak: {weak}")
        print(f"  ⚠️  Reel QA FAIL [{name}] engagement={score} — "
              f"{'; '.join(detail) or overall}")
    else:
        print(f"  ✅ Reel QA {verdict} [{name}] engagement={score} — {overall}")
    # Defects are printed for PASS too — minor issues are still worth a look.
    for d in qa.get("defects", []):
        sev  = str(d.get("severity", "minor")).upper()
        mark = "🔴" if sev == "CRITICAL" else "🟡"
        at   = d.get("at_seconds")
        at_s = f" @{at:.0f}s" if isinstance(at, (int, float)) else ""
        print(f"     {mark} {d.get('type', '?')}{at_s} — {d.get('note', '')}")
