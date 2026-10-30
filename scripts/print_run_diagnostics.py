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
import re
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


_CLUSTERING = re.compile(r"Clustering (\d+) source\(s\) by person identity")
_UNIQUE_PERSONS = re.compile(r"Found (\d+) unique person")
_CLUSTER_WARNING = re.compile(r"Cluster '(.*?)' spans (\d+) clips with confidence=(\w+)")
_VERIFIER_SPLIT = re.compile(r"Identity verification split (\d+) clip\(s\) out of '(.*?)'")
_FRAGMENT_LABEL = re.compile(r"^(.*?)\s+identity-split\s+(\d+)$")


def identity(debug: Path) -> list[str]:
    """How the sources were grouped into athletes, what the verifier changed, and which athletes ended
    up as separate `identity-split` rows (each of which needs its own publishable reel)."""
    try:
        log = (debug / "run_tracked.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        log = ""
    out: list[str] = []
    clustering, found = _CLUSTERING.search(log), _UNIQUE_PERSONS.search(log)
    if clustering or found:
        out.append(f"sources clustered={clustering.group(1) if clustering else '?'} -> "
                   f"unique persons={found.group(1) if found else '?'}")
    splits = [(int(n), desc) for n, desc in _VERIFIER_SPLIT.findall(log)]
    warned = _CLUSTER_WARNING.findall(log)
    if warned:
        out.append("multi-clip clusters (model confidence; the verifier only logs when it splits a cluster):")
        out.append("  cluster                                    clips  confidence  verifier")
        for desc, clips, confidence in warned[:MAX_ROWS]:
            cut = next((n for n, d in splits if desc.startswith(d.rstrip())), 0)
            out.append(f"  {_short(desc, 42):<42} {clips:>5}  {confidence:<10}  "
                       + (f"split {cut} clip(s) off" if cut else "kept together / no split logged"))
    data = _json(debug / "publishable_reel_manifest.json")
    rows = [r for r in (data or {}).get("athletes", []) if isinstance(r, dict)] if isinstance(data, dict) else []
    if rows:
        by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
        fragments = 0
        for row in rows:
            match = _FRAGMENT_LABEL.match(str(row.get("athlete_label") or ""))
            if match:
                fragments += 1
                by_base[match.group(1)].append(row)
        out.append(f"athlete rows in the manifest={len(rows)}; identity-split rows={fragments} from {len(by_base)} cluster(s) "
                   f"(a split row is its own athlete and needs its own publishable reel)")
        for base, items in by_base.items():
            parts = [p for r in items for p in r.get("parts", []) or [] if isinstance(p, dict)]
            ok = sum(1 for p in parts if p.get("publishable"))
            out.append(f"  {_short(base, 52):<52} rows={len(items)} parts={len(parts)} publishable_parts={ok}")
    return out or ["(no identity data in run_tracked.log or publishable_reel_manifest.json)"]


def coverage(debug: Path) -> list[str]:
    data = _json(debug / "athlete_coverage_report.json")
    if not isinstance(data, dict):
        return ["(no athlete_coverage_report.json)"]
    summary = data.get("summary", {})
    out = ["note: 'clusters' = canonical athletes plus every detected person that has no canonical id (source::person); "
           "it is not a count of distinct athletes, and draft_coverage is low when most detected persons have no usable action",
           f"summary: {json.dumps(summary, ensure_ascii=False)[:600]}"]
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


def _qa_notes(part: dict[str, Any]) -> str:
    kinds = [str(d.get("type") or d.get("code")) for d in part.get("qa_defects", []) or [] if isinstance(d, dict)
             and str(d.get("type") or d.get("code")) != "QA_REVIEW_REQUIRED"]
    overall = str(part.get("qa_overall") or "").strip()
    return (f"  | {','.join(kinds[:5])}" if kinds else "") + (f" | {overall[:90]}" if overall else "")


def manifest(debug: Path) -> list[str]:
    data = _json(debug / "publishable_reel_manifest.json")
    if not isinstance(data, dict):
        return ["(no publishable_reel_manifest.json)"]
    out = ["athlete                                   part  qa_verdict  score  dur_s  audio  publishable  issues / QA findings"]
    for row in data.get("athletes", []) or []:
        for part in row.get("parts", []) or []:
            out.append(f"{_short(row.get('athlete_label'), 40):<40} {part.get('part_index')!s:>4}  {_short(part.get('qa_verdict'), 10):<10} "
                       f"{_short(part.get('qa_engagement_score'), 5):>5}  {_short(part.get('duration'), 5):>5}  {_short(part.get('has_audio'), 5):<5}  "
                       f"{_short(part.get('publishable'), 5):<11}  {','.join(str(i) for i in part.get('technical_issues') or [])}"
                       + _qa_notes(part))
    return out


def gate(debug: Path) -> list[str]:
    data = _json(debug / "publishable_reel_gate_result.json")
    if not isinstance(data, dict):
        return ["(no publishable_reel_gate_result.json)"]
    errors = [str(e) for e in data.get("errors", [])]
    kinds = Counter(e.split(": ", 1)[-1][:70] for e in errors)
    head = f"passed={data.get('passed')} errors={len(errors)}"
    if data.get("outcome"):
        head += (f" outcome={data.get('outcome')} mode={data.get('mode')} "
                 f"published_athletes={data.get('publishable_athlete_count')}/{data.get('eligible_athlete_count')} "
                 f"published_parts={data.get('published_part_count')}")
    out = [head, *[f"  {n:>3} × {k}" for k, n in kinds.most_common(12)]]
    gaps = [str(g) for g in data.get("qa_gaps", []) or []]
    if gaps:
        gap_kinds = Counter(g.split(": ", 1)[-1][:70] for g in gaps)
        out.append(f"withheld for QA (not failing the run): {len(gaps)} finding(s)")
        out.extend(f"  {n:>3} × {k}" for k, n in gap_kinds.most_common(12))
    return out


def run_quality(debug: Path) -> list[str]:
    data = _json(debug / "run_quality_report.json")
    if not isinstance(data, dict):
        return ["(no run_quality_report.json)"]
    alerts = data.get("alerts", []) or []
    bugs = data.get("bug_classifications", []) or []
    out = [f"status={data.get('status', 'unknown')} alerts={len(alerts)} bugs={len(bugs)}"]
    if alerts:
        out.append("alerts:")
        for alert in alerts:
            if isinstance(alert, dict):
                out.append(f"  [{_short(alert.get('severity'), 12):<12}] {_short(alert.get('metric'), 36):<36} : {alert.get('reason')}")
    if bugs:
        out.append("bugs:")
        for bug in bugs:
            if isinstance(bug, dict):
                out.append(f"  {_short(bug.get('code'), 36):<36} : {bug.get('evidence')}")
    violations = data.get("mixed_subject_likely_windows", []) or []
    if violations:
        out.append(f"violations ({len(violations)} mixed-subject):")
        for v in violations:
            if isinstance(v, dict):
                out.append(f"  draft={_short(v.get('draft'), 24):<24} primary_track={v.get('primary_track_id')} dominance={v.get('primary_track_dominance_ratio')}")
    duplicates = data.get("duplicate_athlete_likely_drafts", []) or []
    if duplicates:
        out.append(f"violations ({len(duplicates)} same athlete in drafts built from different source pools):")
        for d in duplicates[:10]:
            if isinstance(d, dict):
                out.append(f"  athlete={_short(d.get('athlete_id'), 24):<24} drafts={', '.join(_short(x, 28) for x in (d.get('draft_ids') or [])[:4])}")
    overlaps = data.get("source_window_overlap_duplicates", []) or []
    if overlaps:
        out.append(f"violations ({len(overlaps)} overlapping source windows in different drafts):")
        for o in overlaps[:10]:
            if isinstance(o, dict):
                out.append(f"  {_short(o.get('left_draft'), 26)} ~ {_short(o.get('right_draft'), 26)} overlap={o.get('overlap_seconds')}s "
                           f"({o.get('overlap_ratio_of_shorter')} of the shorter)")
    frag = data.get("track_fragmentation")
    if isinstance(frag, dict) and frag.get("track_count"):
        out.append(f"tracks={frag.get('track_count')} short(<{frag.get('short_track_threshold_sec')}s)={frag.get('short_track_count')} "
                   f"rate={_short(frag.get('short_track_rate'), 6)}")
    schema = data.get("sidecar_schema_errors", []) or []
    if schema:
        out.append(f"sidecar schema errors ({len(schema)}):")
        out.extend(f"  {_short(e, 160)}" for e in schema[:10])
    gaps = [k for k, v in (data.get("implementation_gaps") or {}).items() if v is False]
    if gaps:
        out.append(f"evidence the report could not find: {', '.join(gaps)}")
    return out


_ANALYSIS_FAILED = re.compile(r"Analysis failed for (\S+)")
_ERROR_LINE = re.compile(r"^(?:\d{4}-\d\d-\d\dT[\d:.]+Z )?((?:[A-Za-z_][\w.]*)?(?:Error|Exception)): (.*)$")


def analysis_failures(debug: Path) -> list[str]:
    """Sources whose analysis raised, with the exception that ended it.

    The pipeline logs "Analysis failed for X — will retry" and then drops the source after three tries, so a
    source that fails identically every run is invisible unless the reason is read from the traceback."""
    try:
        lines = (debug / "run_tracked.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ["(no run_tracked.log)"]
    failures: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        found = _ANALYSIS_FAILED.search(line)
        if not found:
            continue
        reason = "(no exception line found after the failure)"
        for follow in lines[index + 1:index + 60]:
            error = _ERROR_LINE.match(follow.strip())
            if error:
                reason = f"{error.group(1)}: {error.group(2)}"
                break
            if _ANALYSIS_FAILED.search(follow):
                break
        failures.append((found.group(1), reason))
    if not failures:
        return ["(no analysis failures)"]
    counts = Counter(reason for _name, reason in failures)
    out = [f"{len(failures)} source(s) failed analysis; {len(counts)} distinct reason(s):"]
    out.extend(f"  {n:>3} x {_short(reason, 150)}" for reason, n in counts.most_common(10))
    out.append("  sources:")
    out.extend(f"    {_short(name, 60):<60} {_short(reason, 90)}" for name, reason in failures[:MAX_ROWS])
    return out


SECTIONS: list[tuple[str, Callable[[Path], list[str]]]] = [
    ("Stage timings (seconds)", stage_timings),
    ("LLM cost", llm_cost),
    ("Run quality report", run_quality),
    ("Source analysis failures", analysis_failures),
    ("Publishable gate result", gate),
    ("Framing decisions", framing),
    ("Reel QA / manifest", manifest),
    ("Selector candidates → ledger", ledger),
    ("Draft windows (trace)", trace),
    ("Athlete coverage", coverage),
    ("Identity clustering", identity),
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
