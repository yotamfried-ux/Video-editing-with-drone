#!/usr/bin/env python3
"""BLK-14-002: least-privilege database role for strict inference (migration not applied by CI; owner action).

D1  the migration never grants anything on public.draft_feedback / public.reprocess_requests and revokes both
D2  it never touches schema ground_truth, and grants no delivery/customer table (athlete_follows, push_tokens, ...)
D3  every table the inference code writes is granted (drafts, reels, pipeline_runs, ... from a scan of .table() calls
    outside the reprocess/feedback/delivery paths) - the role is usable, not just restrictive
D4  key selection: strict + inference key -> inference key (recorded); strict without it -> service key and the
    isolation report says database isolation is NOT in effect; non-strict -> service key
D5  with the inference key the orchestrator's reprocess stage is skipped and recorded (it would need reprocess_requests)
D6  negative control: a migration that grants SELECT on draft_feedback fails D1
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MIGRATION = ROOT / "supabase" / "migrations" / "20261119_inference_role.sql"
FORBIDDEN = ("draft_feedback", "reprocess_requests")
DELIVERY = ("athlete_follows", "push_tokens", "athlete_follow_notifications", "delivery_runs", "payments", "purchases")
FAILS: list[str] = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def code_lines(sql: str) -> list[str]:
    return [l.split("--", 1)[0].strip().lower() for l in sql.splitlines() if l.split("--", 1)[0].strip()]


def grants_on(sql: str, table: str) -> list[str]:
    return [l for l in code_lines(sql) if l.startswith("grant") and re.search(rf"\b{table}\b", l)]


def d1(sql: str) -> bool:
    lines = code_lines(sql)
    return all(not grants_on(sql, t) and any(l.startswith("revoke") and t in l for l in lines) for t in FORBIDDEN)


def main() -> int:
    sql = MIGRATION.read_text()
    check(d1(sql), "D1 draft_feedback / reprocess_requests never granted and explicitly revoked")
    lines = code_lines(sql)
    check(not any("ground_truth" in l for l in lines) and not any(grants_on(sql, t) for t in DELIVERY),
          "D2 no ground_truth access and no delivery/customer table")
    pat = re.compile(r"\.table\([\"']([a-z_]+)[\"']\)\.(?:insert|update|upsert)")
    written = {
        m.group(1)
        for sub in ("pipeline", "integrations")
        for p in (ROOT / sub).rglob("*.py")
        for m in pat.finditer(p.read_text(encoding="utf-8", errors="ignore"))
    }
    needed = written - set(FORBIDDEN) - set(DELIVERY)
    missing = sorted(t for t in needed if not grants_on(sql, t))
    check(not missing, f"D3 every table inference writes is granted (written: {sorted(needed)}; missing: {missing})")

    from pipeline import inference_memory_policy as mp
    os.environ[mp.STRICT_ENV] = "1"
    k1 = mp.database_key("SERVICE", "INFER")
    k2 = mp.database_key("SERVICE", "")
    rep = mp.report()
    os.environ.pop(mp.STRICT_ENV, None)
    k3 = mp.database_key("SERVICE", "INFER")
    check(k1 == "INFER" and k2 == "SERVICE" and k3 == "SERVICE" and rep["database_role"] == "service_role_fallback_not_isolated",
          f"D4 key selection {k1}/{k2}/{k3}; report database_role={rep['database_role']}")

    import config
    from pipeline import orchestrator
    os.environ[mp.STRICT_ENV] = "1"
    old = getattr(config, "SUPABASE_INFERENCE_KEY", "")
    config.SUPABASE_INFERENCE_KEY = "INFER"
    try:
        out = orchestrator._handle_reprocess_requests()
    finally:
        config.SUPABASE_INFERENCE_KEY = old
        os.environ.pop(mp.STRICT_ENV, None)
    skipped = any(e["channel"] == "reprocess_requests" and e["action"] == "stage_skipped_inference_role" for e in mp.events())
    check(out == [] and skipped, "D5 reprocess stage skipped under the inference role (recorded)")
    bad = sql + "\ngrant select on public.draft_feedback to sportreel_inference;\n"
    check(not d1(bad), "D6 negative control: granting draft_feedback is detected")
    print(f"{len(FAILS)} failing")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
