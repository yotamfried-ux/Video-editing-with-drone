#!/usr/bin/env python3
"""Cycle 12 PA-01: proposed policy for people who are in no catalogue / GT cohort (UNCATALOGUED-PERSON-POLICY.md).

The pipeline already reels every tracked person; this contract pins the SEPARATION of the stages so the commercial
goal (a reel for everyone with a valid action) can never become an identity or GT shortcut:

U1  candidate reel: a valid action of a person with no catalogue / GT id is eligible (eligibility never consults a
    catalogue or a GT athlete id)
U2  a valid action needs its own evidence: no positive evidence -> UNCERTAIN (reviewed); an explicit failed attempt
    -> INELIGIBLE (same rule for every person)
U3  no automatic account binding: a pipeline athlete is scoped to <recording date>:<run athlete id>; two keys with
    the SAME description get DIFFERENT athletes (no join by description, appearance or face); only the same key
    reuses an athlete; joining across sessions is an operator action
U4  no biometric identifier in any live runtime path (scripts/verify_no_biometric_runtime_dependencies.py)
U5  approval and distribution stay with the operator: no pipeline module writes approved/ or publishes; the
    pipeline's publish entry points are reached only from the delivery job after operator approval
U6  scoring: a reel of a person outside GT-v1 is reported apart (publishable_non_gt_person) and never counted as a
    GT success (quality_scorecard)
"""
from __future__ import annotations

import ast
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def main() -> int:
    from pipeline import performance_reel_policy as prp

    ride = {"type": "surf_ride", "score": 8, "description": "rides the wave", "person_id": "person_A"}
    import inspect
    fn = ast.parse(inspect.getsource(prp.classify_event_eligibility).strip()).body[0]
    if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(getattr(fn.body[0], "value", None), ast.Constant):
        fn.body = fn.body[1:]                     # the code, not the docstring prose
    elig_src = ast.unparse(fn).lower()
    check(prp.classify_event_eligibility(ride, "surfing")["verdict"] == "ELIGIBLE"
          and not any(w in elig_src for w in ("catalog", "athlete_id", "ground_truth", "gt_")),
          "U1 a valid action of a person with no catalogue / GT id is eligible; eligibility has no catalogue input")
    check(prp.classify_event_eligibility({"type": "surf_ride", "score": 3}, "surfing")["verdict"] == "UNCERTAIN"
          and prp.classify_event_eligibility({"type": "wave_catch", "description": "failed takeoff", "score": 9}, "surfing")["verdict"] == "INELIGIBLE",
          "U2 no positive evidence -> UNCERTAIN (reviewed); explicit failed attempt -> INELIGIBLE")

    try:
        from supabase import create_client  # noqa: F401
    except Exception:  # CI jobs without the client library: the policy under test never calls it
        stub = types.ModuleType("supabase")
        stub.create_client = lambda *a, **k: None
        stub.Client = object
        sys.modules["supabase"] = stub
    from integrations import supabase_uploader as su

    class Q:
        def __init__(self, db, table):
            self.db, self.table, self.filters, self.payload = db, table, {}, None
        def select(self, *a): return self
        def eq(self, k, v): self.filters[k] = v; return self
        @property
        def not_(self): return self
        def is_(self, *a): return self
        def limit(self, *a): return self
        def insert(self, row): self.payload = row; return self
        def execute(self):
            if self.payload is not None:
                self.db.setdefault(self.table, []).append(self.payload)
                return types.SimpleNamespace(data=[self.payload])
            rows = [r for r in self.db.get("reels", []) if all(r.get(k) == v for k, v in self.filters.items())]
            return types.SimpleNamespace(data=rows)

    db: dict = {"reels": []}
    su._supabase = lambda: types.SimpleNamespace(table=lambda t: Q(db, t))
    a1 = su._resolve_athlete("2026-07-20:ath_x", "Man in a white long-sleeve top")
    db["reels"].append({"athlete_key": "2026-07-20:ath_x", "athlete_id": a1})
    a2 = su._resolve_athlete("2026-07-21:ath_y", "Man in a white long-sleeve top")
    a3 = su._resolve_athlete("2026-07-20:ath_x", "another description")
    check(a1 != a2 and a1 == a3 and su._resolve_athlete(None, "x") is None,
          "U3 same description, different session key -> different athlete; only the exact key reuses one; no key -> none")

    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_no_biometric_runtime_dependencies.py")],
                         capture_output=True, text=True, timeout=120)
    check(out.returncode == 0, "U4 no biometric identifier in live runtime paths")

    writers = []
    for path in list((ROOT / "pipeline").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("approved/"):
                writers.append(str(path.relative_to(ROOT)))
    publish_callers = [str(p.relative_to(ROOT)) for p in (ROOT / "pipeline").rglob("*.py")
                       if "publish_reel(" in p.read_text() or "publish_to_discover" in p.read_text()]
    allowed = {"pipeline/draft_ledger.py"}   # reads approved/ to recognise an operator approval, never writes it
    check(set(writers) <= allowed and not publish_callers,
          f"U5 no pipeline module writes approved/ or publishes (approved/ literals: {sorted(set(writers))}; publish callers: {publish_callers})")
    import inspect
    from pipeline import draft_ledger
    src = inspect.getsource(draft_ledger.publish)
    check("upload_review" in src and "APPROVED_PREFIX + " not in src.replace("(REVIEW_PREFIX, APPROVED_PREFIX)", ""),
          "U5 the draft ledger only uploads to review/ (approved/ is read, never written)")

    qs = (ROOT / "scripts" / "quality_scorecard.py").read_text()
    check("publishable_non_gt_person" in qs and "qa_false_pass_gt_cohort" in qs and '"publishable_correct": m["published_correct"]' in qs,
          "U6 scorecard reports non-GT-person reels apart and never adds them to publishable_correct")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
