#!/usr/bin/env python3
"""Print the run's key diagnostics into the job log (and the step summary).

The pipeline-diagnostics artifact is stored on blob storage that automation outside GitHub cannot always
fetch, but the job log can always be read. This prints a bounded, human-readable digest of everything
needed to explain a run: where the time went, what the LLM cost, which selector candidates matched which
drafts, why athletes were or were not accounted for, how each clip was framed, and the QA verdicts.
Never fails the job: every section is best-effort.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

MAX_ROWS = 120


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError:
        pass
    return rows


def _win(window: Any) -> str:
    if not isinstance(window, dict) or window.get("start") is None or window.get("end") is None:
        return "-"
    return f"{float(window['start']):.1f}-{float(window['end']):.1f}"


def _short(value: Any, n: int = 34) -> str:
    return str(value if value is not None else "-")[:n]


def stage_timings(debug: Path) -> list[str]:
    rows = _jsonl(debug / "stage_timings.jsonl")
    if not rows:
        return ["(no stage_timings.jsonl)"]
    by_stage: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_stage[str(row.get("stage"))].append(float(row.get("seconds") or 0.0))
    out = ["stage                      n    total_s     max_s"]
    for stage, values in sorted(by_stage.items(), key=lambda kv: -sum(kv[1])):
        out.append(f"{stage:<24} {len(values):>4} {sum(values):>10.0f} {max(values):>9.0f}")
    return out


def llm_cost(debug: Path) -> list[str]:
    rows = _jsonl(debug / "llm_cost_calls.jsonl")
    if not rows:
        return ["(no llm_cost_calls.jsonl)"]
    by_label: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_label[(str(row.get("label")), str(row.get("model")))].append(row)
    total = sum(float(r.get("cost_usd") or 0.0) for r in rows)
    out = [f"total ≈ ${total:.4f} over {len(rows)} calls", "label / model                                   calls  prompt_tok  think_tok   cost_usd"]
    for (label, model), items in sorted(by_label.items(), key=lambda kv: -sum(float(r.get("cost_usd") or 0) for r in kv[1])):
        out.append(f"{label[:30]:<30} {model[:16]:<16} {len(items):>5} {sum(int(r.get('prompt_tokens') or 0) for r in items):>10} "
                   f"{sum(int(r.get('thinking_tokens') or 0) for r in items):>10} {sum(float(r.get('cost_usd') or 0) for r in items):>10.4f}")
    return out


def ledger(debug: Path) -> list[str]:
    data = _json(debug / "candidate_decision_ledger.json")
    if not isinstance(data, dict):
        return ["(no candidate_decision_ledger.json)"]
    candidates = [c for c in data.get("candidates", []) if isinstance(c, dict)]
    causes = Counter(str(c.get("discard_cause")) for c in candidates if c.get("discarded"))
    out = [f"candidates={len(candidates)} selected={data.get('selected_count')} discarded={data.get('discarded_count')} "
           f"unmatched_selector_selected={data.get('unmatched_selector_selected_count')}",
           "discard causes: " + ", ".join(f"{k}={v}" for k, v in causes.most_common()),
           "state  cause/draft                         source                              person        window         type        athlete"]
    for c in candidates[:MAX_ROWS]:
        state = "SEL " if c.get("selected") else "DISC"
        tail = _short(c.get("draft_name") if c.get("selected") else c.get("discard_cause"), 34)
        out.append(f"{state}  {tail:<34} {_short(c.get('source_video'), 34):<34} {_short(c.get('person_id'), 12):<12} "
                   f"{_win(c.get('source_window')):<13} {_short(c.get('event_type'), 11):<11} {_short(c.get('athlete_id'), 14)}"
                   + ("  [overlap-matched]" if c.get("matched_via_window_overlap") else ""))
    return out


def trace(debug: Path) -> list[str]:
    data = _json(debug / "draft_decision_trace.json")
    if not isinstance(data, dict):
        return ["(no draft_decision_trace.json)"]
    out = ["draft                              source                              person        window         original       type"]
    n = 0
    for draft in data.get("drafts", []) or []:
        for w in draft.get("source_windows", []) or []:
            if not isinstance(w, dict):
                continue
            original = {"start": w.get("original_start"), "end": w.get("original_end")}
            out.append(f"{_short(draft.get('draft_name'), 34):<34} {_short(w.get('source_video'), 34):<34} {_short(w.get('person_id'), 12):<12} "
                       f"{_win(w):<13} {_win(original):<13} {_short(w.get('event_type'), 12)}")
            n += 1
            if n >= MAX_ROWS:
                return out
    return out


def coverage(debug: Path) -> list[str]:
    data = _json(debug / "athlete_coverage_report.json")
    if not isinstance(data, dict):
        return ["(no athlete_coverage_report.json)"]
    summary = data.get("summary", {})
    out = [f"summary: {json.dumps(summary, ensure_ascii=False)[:600]}"]
    gaps = [a for a in data.get("athletes", []) if isinstance(a, dict) and a.get("candidate_action_count", 0) > 0
            and not a.get("coverage_requirement_met")]
    out.append(f"unresolved clusters: {len(gaps)}")
    for a in gaps[:MAX_ROWS]:
        out.append(f"  {_short(a.get('athlete_cluster_id'), 56):<56} cand={a.get('candidate_action_count')} sel={a.get('selected_action_count')} "
                   f"reason={a.get('no_output_reason')} explicit={a.get('no_output_reason_explicit')}")
    return out


def framing(debug: Path) -> list[str]:
    rows = _jsonl(debug / "framing_decisions.jsonl")
    if not rows:
        return ["(no framing_decisions.jsonl)"]
    modes = Counter(str(r.get("mode")) for r in rows)
    reasons = Counter(str(r.get("reason")) for r in rows)
    heights = sorted(float(r.get("athlete_height_ratio") or 0.0) for r in rows)
    median = heights[len(heights) // 2] if heights else 0.0
    return [f"clips={len(rows)} modes: " + ", ".join(f"{k}={v}" for k, v in modes.items()),
            "reasons: " + ", ".join(f"{k}={v}" for k, v in reasons.most_common(8)),
            f"athlete height as share of source frame: median={median:.3f} min={heights[0]:.3f} max={heights[-1]:.3f}"]


def manifest(debug: Path) -> list[str]:
    data = _json(debug / "publishable_reel_manifest.json")
    if not isinstance(data, dict):
        return ["(no publishable_reel_manifest.json)"]
    out = ["athlete                                   part  qa_verdict  score  dur_s  audio  publishable  issues"]
    for row in data.get("athletes", []) or []:
        for part in row.get("parts", []) or []:
            out.append(f"{_short(row.get('athlete_label'), 40):<40} {part.get('part_index')!s:>4}  {_short(part.get('qa_verdict'), 10):<10} "
                       f"{_short(part.get('qa_engagement_score'), 5):>5}  {_short(part.get('duration'), 5):>5}  {_short(part.get('has_audio'), 5):<5}  "
                       f"{_short(part.get('publishable'), 5):<11}  {','.join(str(i) for i in part.get('technical_issues') or [])}")
    return out


def gate(debug: Path) -> list[str]:
    data = _json(debug / "publishable_reel_gate_result.json")
    if not isinstance(data, dict):
        return ["(no publishable_reel_gate_result.json)"]
    errors = [str(e) for e in data.get("errors", [])]
    kinds = Counter(e.split(": ", 1)[-1][:70] for e in errors)
    return [f"passed={data.get('passed')} errors={len(errors)}", *[f"  {n:>3} × {k}" for k, n in kinds.most_common(12)]]


SECTIONS: list[tuple[str, Callable[[Path], list[str]]]] = [
    ("Stage timings (seconds)", stage_timings),
    ("LLM cost", llm_cost),
    ("Publishable gate result", gate),
    ("Framing decisions", framing),
    ("Reel QA / manifest", manifest),
    ("Selector candidates → ledger", ledger),
    ("Draft windows (trace)", trace),
    ("Athlete coverage", coverage),
]


def main() -> int:
    debug = Path(os.getenv("TMP_DIR", "/tmp/dtor")) / "pipeline-debug"
    lines: list[str] = []
    for title, builder in SECTIONS:
        lines.append(f"::group::DIAG {title}")
        try:
            lines.extend(builder(debug))
        except Exception as exc:  # a diagnostics bug must never fail the job
            lines.append(f"(section failed: {type(exc).__name__}: {exc})")
        lines.append("::endgroup::")
    text = "\n".join(lines)
    print(text)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write("## Run diagnostics\n\n```\n" + "\n".join(l for l in lines if not l.startswith("::")) + "\n```\n")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
