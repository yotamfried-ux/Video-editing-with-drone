#!/usr/bin/env python3
"""Run the T01-T15 release test matrix (spec docs/plans/2026-11-15-pipeline-root-causes-and-preventive-architecture.md §4).

Each test id maps to the contract tests that exercise it through production functions (or the real bootstrap), the
real-video evidence that exists, and what remains blocked. Writes release_matrix.json with the commit it ran on, so
every result refers to one code revision. A test id passes only if all of its contracts pass on this revision; real
video is reported separately and never inferred from contracts.

usage: run_release_matrix.py [--out FILE] [--node-suite DIR:TEST]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MATRIX: dict[str, dict] = {
    "T01": {"name": "negative eligible action", "fixture": "0095 (no meaningful action), 0155 (failed takeoff)",
            "contracts": ["test_output_qualification_contract.py", "test_root_cause_fixes_contract.py"],
            "real_video": "baseline only: frozen GT-v1 evaluation of runs 43710581656/43816344303 shows 0095 (348/379) "
                          "and 0155 (420/476 frames) selected; no run on the fixed code",
            "limitation": "0095/0155 carry analyzer ratings 9/7: whether CV activity marks them UNCERTAIN needs a run "
                          "and visual review"},
    "T02": {"name": "excluded subwindow", "fixture": "0108 after 6.82 s",
            "contracts": ["test_output_qualification_contract.py"],
            "real_video": "baseline only: 0108 excluded tail 131/144 frames selected in both runs",
            "limitation": "tail beyond verified actor is blocked; a tail where the actor stays visible is not detected "
                          "without visual evidence"},
    "T03": {"name": "same-source handoff", "fixture": "0094 two GT identities",
            "contracts": ["test_output_qualification_contract.py", "test_release_safety_invariants_contract.py"],
            "real_video": "none on fixed code", "limitation": "handoff inside one track id is caught only via track gap"},
    "T04": {"name": "cross-source false merge", "fixture": "0143 + 0152",
            "contracts": ["test_release_safety_invariants_contract.py", "test_verified_cluster_merge_contract.py",
                          "test_identity_merge_check_contract.py"],
            "real_video": "run 43816344303: image verifier confirmed 0143+0152 (GT: two athletes) -> VISUAL_REVIEW_REQUIRED",
            "limitation": "a confident wrong image verdict is not caught by code"},
    "T05": {"name": "cross-source false split", "fixture": "0097 + 0115",
            "contracts": ["test_release_safety_invariants_contract.py", "test_identity_merge_check_contract.py"],
            "real_video": "runs show a missed merge (GT: one athlete) -> VISUAL_REVIEW_REQUIRED", "limitation": "recall of merges"},
    "T06": {"name": "weak / fragmented track", "fixture": "0094, 0140, 0115, whitewash",
            "contracts": ["test_output_qualification_contract.py", "test_missed_moment_rescue_contract.py"],
            "real_video": "none on fixed code", "limitation": "no verified per-frame box GT (UNVERIFIED_GT)"},
    "T07": {"name": "action boundary", "fixture": "0115, 0151, 0104, camera end",
            "contracts": ["test_output_qualification_contract.py", "test_missed_moment_rescue_contract.py"],
            "real_video": "baseline: 24/24 physical rides covered (GT-v1)", "limitation": "frame-tolerance not measured"},
    "T08": {"name": "stable lineage", "fixture": "candidate -> EDL -> QA -> reel",
            "contracts": ["test_release_safety_invariants_contract.py", "test_output_qualification_contract.py",
                          "test_reprocess_binding_contract.py"],
            "real_video": "run 43816344303: 25/25 EDL shots carry ev2_ ids", "limitation": "QA trace/manifest ids since #389, not yet in a run"},
    "T09": {"name": "QA resolution", "fixture": "duplicate request, timeout, no-op rerender, wrong repaired athlete",
            "contracts": ["test_reprocess_binding_contract.py", "test_repair_lifecycle_contract.py"],
            "real_video": "none", "limitation": "no reprocess run on the fixed code"},
    "T10": {"name": "gate bypass", "fixture": "QA PASS but actor failed; execution success but product partial",
            "contracts": ["test_output_qualification_contract.py", "test_batch_qualification_contract.py",
                          "test_qa_gate_block_not_publishable_contract.py", "test_business_gate_qa_fix.py"],
            "real_video": "run 43816344303 re-qualified offline: execution SUCCESS, product FAIL (0/14 verified)",
            "limitation": "approval API reads technical_issues; proof digest not yet stored server-side (needs a migration)"},
    "T11": {"name": "wrapper precedence", "fixture": "tracked, manual, reset entrypoints",
            "contracts": ["test_runtime_policy_registry_contract.py", "test_bootstrap_parity_contract.py",
                          "test_pipeline_logical_consistency_integration.py"],
            "real_video": "none", "limitation": "registry artifact first produced by the next real run"},
    "T12": {"name": "GT integrity", "fixture": "frozen GT-v1 (24 sources)",
            "contracts": ["test_gt_evidence_levels_contract.py"], "node": True,
            "real_video": "offline evaluation of both runs, deterministic digests",
            "limitation": "box GT is UNVERIFIED_GT; the evaluator's own tests run in the GT Studio CI workflow "
                          "(pipeline code may not reference the Studio), or here with --node-suite DIR:TEST"},
    "T13": {"name": "media contract", "fixture": "2160x3840 30 fps silent",
            "contracts": ["test_silent_output_policy_contract.py", "test_quality_first_4k_media_contract.py"],
            "real_video": "previous runs (ffprobe in manifest)", "limitation": "encoded quality judged visually"},
    "T14": {"name": "historical QA backlog", "fixture": "202 existing rows",
            "contracts": ["test_repair_lifecycle_contract.py", "test_reprocess_binding_contract.py"],
            "real_video": "n/a", "limitation": "legacy rows need operator reconciliation"},
    "T15": {"name": "cost and failure", "fixture": "timeout, DB outage, worker crash",
            "contracts": ["test_reprocess_binding_contract.py", "test_cost_time_optimizations_contract.py"],
            "real_video": "n/a", "limitation": "storage outage covered only by existing upload tests"},
}


def run(cmd: list[str], cwd: Path) -> tuple[bool, str]:
    env = {**os.environ, "PYTHONPATH": f"{ROOT}/scripts:{ROOT}"}
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    tail = (p.stdout + p.stderr).strip().splitlines()[-1:] or [""]
    return p.returncode == 0, tail[0][:200]


def main() -> int:
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ROOT / "release_matrix.json"
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    # The GT Studio is isolated from pipeline code: its evaluator suite is passed in, never named here.
    node_suite = sys.argv[sys.argv.index("--node-suite") + 1] if "--node-suite" in sys.argv else ""
    cache: dict[str, tuple[bool, str]] = {}
    rows = {}
    for tid, spec in MATRIX.items():
        results = {}
        for name in spec["contracts"]:
            if name not in cache:
                cache[name] = run([sys.executable, f"scripts/{name}"], ROOT)
            results[name] = {"pass": cache[name][0], "last_line": cache[name][1]}
        if spec.get("node") and node_suite:
            folder, test = node_suite.split(":", 1)
            key = f"{folder}/{test}"
            if key not in cache:
                cache[key] = run(["node", "--disable-warning=ExperimentalWarning", "--test", test], ROOT / folder)
            results[key] = {"pass": cache[key][0], "last_line": cache[key][1]}
        rows[tid] = {**{k: v for k, v in spec.items() if k not in {"contracts", "node"}},
                     "contracts": results, "contracts_pass": all(r["pass"] for r in results.values()),
                     "real_video_on_fixed_code": False}
    body = {"commit": commit, "matrix": rows, "all_contracts_pass": all(r["contracts_pass"] for r in rows.values())}
    out.write_text(json.dumps(body, indent=2), encoding="utf-8")
    for tid, r in rows.items():
        print(f"{tid} {'PASS' if r['contracts_pass'] else 'FAIL'} contracts | real video on fixed code: no | {r['name']}")
    return 0 if body["all_contracts_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
