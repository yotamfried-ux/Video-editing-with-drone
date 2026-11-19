#!/usr/bin/env python3
"""MEM-03 negative controls: deliberate attempts to feed prior-run memory or evaluation material into inference.

Each probe runs in its own subprocess twice: CONTROL (strict off) must SEE the planted memory - this proves the probe
can detect a leak - and STRICT (SPORTREEL_STRICT_COLD_INFERENCE=1) must NOT see it.

M1  operator notes for an earlier draft            -> analysis prompt block
M2  approval / edit history (labels_feedback.json) -> analysis prompt block
M3  structured draft_feedback rows (Supabase)      -> analysis prompt block
M4  QA calibration history                         -> QA prompt hint (strict: closed and recorded)
M5  manual identity decision file (non-qualification-only) -> identity decisions
M6  planted cross-run model answer in the LLM cache for the same key
M7  a perception sidecar older than this run       -> not reused (recomputed)
M8  opening Ground Truth / qualification / evidence files from the inference process (open(), Path.read_text,
    os.open) -> ForbiddenInferenceInput, even though the files exist
M9  the inference isolation report lists every closed channel, refused open and rejected sidecar
M10 hidden evaluation files through symlink or parent traversal -> blocked in strict mode
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAILS: list[str] = []
MARK = "MARKER_PRIOR_RUN_QZX"


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


PROBE = textwrap.dedent(r'''
import json, os, sys, time, types
from pathlib import Path
sys.path.insert(0, os.environ["REPO"])
work = Path(os.environ["WORK"]); MARK = os.environ["MARK"]
import config
config.FEEDBACK_FILE = str(work / "labels_feedback.json")
config.OPERATOR_NOTES_FILE = str(work / "operator_notes.json")
config.QA_RESULTS_FILE = str(work / "qa_results.jsonl")
from pipeline import inference_memory_policy as memory
memory.install_guard()
out = {}
try:
    from supabase import create_client  # noqa: F401
except Exception:   # CI jobs without the client: the probe monkeypatches the only reader it needs
    stub = types.ModuleType("supabase"); stub.create_client = lambda *a, **k: None; stub.Client = object
    sys.modules["supabase"] = stub
from pipeline.stages import feedback
out["notes"] = feedback.get_operator_notes()
out["labels"] = feedback.get_all_label_injections()
import integrations.supabase_uploader as su
su.fetch_recent_draft_feedback = lambda limit=500: [{"feedback_event": e, "created_at": "2026-11-18T00:00:00+00:00"}
    for e in list(feedback._PROBLEM_EVENTS)[:1] * 40]
out["draft_feedback"] = feedback.get_negative_feedback_hint()
out["qa_hint"] = feedback.get_qa_calibration_hint("surfing")
from pipeline import identity_review
out["decisions"] = len(identity_review.load_decisions(str(work / "decisions.json")))
from integrations import llm_cache
key = llm_cache.make_key("analysis", media_sha256="a" * 64, prompt="p", model="m")
llm_cache.put(key, MARK) if llm_cache.enabled() else None
out["cache_hit"] = (llm_cache.get(key) if llm_cache.enabled() else None) == MARK
old = work / "old.perception.json"; old.write_text("{}"); os.utime(old, (time.time() - 3600,) * 2)
new = work / "new.perception.json"; new.write_text("{}")
out["old_sidecar_reused"] = memory.sidecar_reusable(old)
out["new_sidecar_reused"] = memory.sidecar_reusable(new)
gt = Path(os.environ["REPO"]) / "evaluation" / "ground_truth" / "gtv1_frozen.json"
refused = []
for name, fn in (("open", lambda: open(gt).read(1)), ("read_text", lambda: gt.read_text()[:1]),
                 ("os.open", lambda: os.close(os.open(str(gt), os.O_RDONLY)))):
    try:
        fn(); refused.append(False)
    except memory.ForbiddenInferenceInput:
        refused.append(True)
out["gt_refused"] = refused
out["gt_exists"] = gt.exists()
# These aliases do not contain the literal forbidden path. A string-only guard misses both.
alias_paths = (work / "alias_to_eval", work / "evaluation" / "safe" / ".." / "ground_truth" / "private.json")
refused_aliases = []
for alias_path in alias_paths:
    try:
        alias_path.read_text()
        refused_aliases.append(False)
    except memory.ForbiddenInferenceInput:
        refused_aliases.append(True)
out["aliased_gt_refused"] = refused_aliases
memory.write_report(work / "report.json")
print("RESULT " + json.dumps(out))
''')


def run_probe(strict: bool) -> tuple[dict, dict]:
    work = Path(tempfile.mkdtemp(prefix="mem03-"))
    (work / "operator_notes.json").write_text(json.dumps({"DRAFT_old": {"note": MARK, "ts": "2026-11-18T00:00:00+00:00"}}))
    (work / "labels_feedback.json").write_text(json.dumps({"approvals": [
        {"ts": "2026-11-18T00:00:00+00:00", "sport": "surfing", "events": [{"type": MARK.lower(), "edit": {"zoom": 1.0}}]}] * 4}))
    (work / "decisions.json").write_text(json.dumps({"decisions": [{"request_id": "b" * 64, "decision": "APPROVED",
                                                                   "reviewer": "owner", "decided_at": "2026-11-18"}]}))
    # Protect a non-special filename inside an evaluation directory to expose alias bypasses.
    hidden_dir = work / "evaluation" / "ground_truth"
    hidden_dir.mkdir(parents=True)
    (work / "evaluation" / "safe").mkdir()
    hidden_file = hidden_dir / "private.json"
    hidden_file.write_text(MARK)
    (work / "alias_to_eval").symlink_to(hidden_file)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SPORTREEL_")}
    env.update(REPO=str(ROOT), WORK=str(work), MARK=MARK, LLM_CACHE="1", LLM_CACHE_DIR=str(work / "cache"),
               TMP_DIR=str(work), PYTHONPATH=str(ROOT))
    if strict:
        env["SPORTREEL_STRICT_COLD_INFERENCE"] = "1"
    proc = subprocess.run([sys.executable, "-c", PROBE], capture_output=True, text=True, env=env, cwd=str(work), timeout=180)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT ")), None)
    if line is None:
        print(proc.stdout[-2000:], proc.stderr[-3000:])
        return {}, {}
    report = json.loads((work / "report.json").read_text()) if (work / "report.json").exists() else {}
    return json.loads(line[7:]), report


def main() -> int:
    c, _ = run_probe(False)
    s, rep = run_probe(True)
    check(MARK in c.get("notes", "") and not s.get("notes"), "M1 operator notes: control sees the planted note, strict sees nothing")
    check(MARK.lower() in c.get("labels", "") and not s.get("labels"), "M2 approval history: control injected, strict closed")
    check(bool(c.get("draft_feedback")) and not s.get("draft_feedback"), "M3 draft_feedback rows: control hint, strict closed")
    check(not s.get("qa_hint") and "qa_calibration_history" in rep.get("channels_closed", []), "M4 QA calibration history closed and recorded")
    check(c.get("decisions") == 1 and s.get("decisions") == 0, "M5 manual identity decision file: control loads 1, strict loads none")
    check(c.get("cache_hit") is True and s.get("cache_hit") is False, "M6 planted cross-run cache answer: control hit, strict miss")
    check(c.get("old_sidecar_reused") is True and s.get("old_sidecar_reused") is False and s.get("new_sidecar_reused") is True,
          "M7 sidecar older than the run is not reused under strict; one written in this run is")
    check(s.get("gt_exists") is True and s.get("gt_refused") == [True, True, True] and c.get("gt_refused") == [False, False, False],
          f"M8 GT open refused under strict via open/read_text/os.open (control can read it): {s.get('gt_refused')}")
    check(s.get("aliased_gt_refused") == [True, True] and c.get("aliased_gt_refused") == [False, False],
          f"M10 symlink and parent-traversal GT aliases refused in strict mode: {s.get('aliased_gt_refused')}")
    check(rep.get("strict_cold_inference") is True and rep.get("guard_installed") is True
          and {"operator_notes", "draft_feedback", "label_feedback_history", "identity_decisions"} <= set(rep.get("channels_closed", []))
          and len(rep.get("open_refused", [])) >= 3 and rep.get("prior_sidecars_rejected"),
          f"M9 isolation report complete (closed {rep.get('channels_closed')})")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
