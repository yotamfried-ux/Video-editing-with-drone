#!/usr/bin/env python3
"""Cycle 10 Gate A: same-namespace retry and deliberate mid-run crashes of the PRODUCTION pipeline, free (budget 0).

  inventory --run-id ID --phase P --exit-code N --tmp DIR --out FILE
        object listing of qualification/<ID>/ (key, size, etag) by logical prefix + this phase's ledger summary
  evaluate --dir DIR --out FILE
        applies the Gate A checks to the phase inventories written by scripts/qualification_gate_a.sh

Phases (each one a fresh TMP_DIR = a fresh runner, as after a real crash):
  R0  retry into the EXISTING namespace q9-dry-02 (that run completed): must be a no-op (no input, zero writes)
  F1  crash after analysis (before any output)        F2  crash before the QA gate of the first athlete
  F3  crash right after the FIRST draft upload        R4  recovery run, same namespace, no fault
  R5  retry after the completed recovery: must be a no-op
Cycle 12 PA-13 suite (run_config gate_a_suite = "pa13"; scripts/qualification_gate_a.sh):
  L1/L2  legacy names (SPORTREEL_DRAFT_LEDGER=0, namespace <id>-legacy): crash after the first upload, then a retry
         with another description suffix and date -> expected RED (left-over drafts next to renamed ones)
  G1/G2  the same with the draft ledger -> no renamed duplicate, partials kept, same output count
  G3     retry after completion -> no-op
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _ledger(tmp: Path) -> list[dict]:
    path = tmp / "pipeline-debug" / "qualification_ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def inventory(run_id: str, phase: str, exit_code: int, tmp: Path, out: Path) -> int:
    import qualification_run as qr
    client, bucket = qr._raw_client()
    ns = qr._ns(run_id)
    objs = sorted((o["Key"][len(ns):], o["Size"], o.get("ETag")) for o in qr._list(client, bucket, ns))
    by_prefix = collections.defaultdict(list)
    for key, size, etag in objs:
        by_prefix[key.split("/", 1)[0] + "/"].append([key, size, etag])
    led = _ledger(tmp)
    kinds = collections.Counter(e["kind"] for e in led)
    writes = [e for e in led if e["kind"] == "r2_write"]
    blocked = collections.Counter(e.get("table") for e in led if e["kind"] == "supabase_write_blocked")
    # A record that would make a draft publishable (run 44148876075: a substring match on "pass" also counted
    # "qa_passed": false records, a false positive). Only publishable == True or qa_passed == True counts.
    def _grants(payload):
        rows = payload if isinstance(payload, list) else [payload]
        return any(isinstance(r, dict) and (r.get("publishable") is True or r.get("qa_passed") is True) for r in rows)
    pass_records = [e for e in led if e["kind"] == "supabase_write_blocked" and e.get("table") == "draft_publishability"
                    and _grants(e.get("payload"))]
    log = tmp / "pipeline-debug" / "run_tracked.log"
    text = log.read_text(errors="replace") if log.exists() else ""
    report = {
        "phase": phase, "run_id": run_id, "exit_code": exit_code,
        "objects": {p: v for p, v in sorted(by_prefix.items())},
        "counts": {p: len(v) for p, v in sorted(by_prefix.items())},
        "ledger_kinds": dict(kinds),
        "r2_writes": [[w.get("op"), str(w.get("key", ""))[len(ns):] if str(w.get("key", "")).startswith(ns) else w.get("key")]
                      for w in writes],
        "r2_writes_outside_namespace": [w.get("key") for w in writes if not str(w.get("key", "")).startswith(ns)],
        "supabase_blocked_by_table": dict(blocked),
        "publishability_pass_payloads": len(pass_records),
        "faults": [e.get("point") for e in led if e["kind"] == "fault_injected"],
        "no_input": "No new videos" in text,
        "drafts_line": next((l for l in text.splitlines() if "draft(s) uploaded" in l), ""),
    }
    out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("phase", "exit_code", "counts", "faults", "no_input", "drafts_line")}))
    return 0


def _keys(inv: dict, prefix: str) -> dict[str, tuple]:
    return {k: (s, e) for k, s, e in inv["objects"].get(prefix, [])}


def evaluate(d: Path, out: Path) -> int:
    inv = {p.name[: -len(".inventory.json")]: json.loads(p.read_text()) for p in sorted(d.glob("*.inventory.json"))}
    checks: list[dict] = []

    def check(cid: str, ok: bool, detail: str) -> None:
        checks.append({"id": cid, "pass": bool(ok), "detail": detail})

    # R0: retry into a completed namespace
    a, b = inv.get("R0-before"), inv.get("R0")
    if a and b:
        check("A1.R0.no_input", b["no_input"] and b["exit_code"] == 0, f"exit={b['exit_code']} no_input={b['no_input']}")
        check("A1.R0.no_writes", not b["r2_writes"], f"r2 writes={len(b['r2_writes'])}")
        check("A1.R0.namespace_unchanged", a["objects"] == b["objects"], "object listing identical before/after the retry")
    raw0 = _keys(inv["seed"], "raw/") if "seed" in inv else None
    # the cycle-10 crash phases are checked only in the suite that runs them (the pa13 suite runs L*/G* instead;
    # run 44269495332 reported "phase inventory missing" for F1-F3 although the pa13 suite never schedules them)
    cycle10 = any(p in inv for p in ("R0", "F1", "F2", "F3", "R4", "R5"))
    for phase, point in ((("F1", "after_analysis"), ("F2", "before_qa"), ("F3", "after_first_upload")) if cycle10 else ()):
        x = inv.get(phase)
        if not x:
            check(f"A2.{phase}.ran", False, "phase inventory missing")
            continue
        check(f"A2.{phase}.crashed_at_point", x["exit_code"] == 97 and x["faults"] == [point],
              f"exit={x['exit_code']} faults={x['faults']}")
        check(f"A2.{phase}.no_processed_markers", x["counts"].get("metadata/", 0) == 0 or not any(
            k.startswith("metadata/source_state/") for k in _keys(x, "metadata/")),
              f"metadata objects={x['counts'].get('metadata/', 0)}")
        check(f"A2.{phase}.no_publishable_state", x["publishability_pass_payloads"] == 0,
              f"PASS publishability payloads={x['publishability_pass_payloads']}")
        check(f"A2.{phase}.writes_confined", not x["r2_writes_outside_namespace"], "every write inside the namespace")
        if raw0 is not None:
            check(f"A2.{phase}.raw_unchanged", _keys(x, "raw/") == raw0, "namespace raw/ identical to the seed")
    if "F1" in inv:
        check("A2.F1.no_outputs", inv["F1"]["counts"].get("review/", 0) == 0, f"review objects={inv['F1']['counts'].get('review/', 0)}")
    if "F2" in inv:
        check("A2.F2.no_outputs", inv["F2"]["counts"].get("review/", 0) == 0, f"review objects={inv['F2']['counts'].get('review/', 0)}")
    if "F3" in inv:
        # Uploads run on up to _MAX_UL_WORKERS threads, so a hard crash at the first completed upload leaves between 1
        # and that many objects; every one must be a non-publishable partial that the recovery run rewrites (R4 below).
        import re as _re
        orch = (ROOT / "pipeline" / "orchestrator.py").read_text()
        m = _re.search(r"_MAX_UL_WORKERS\s*=\s*(\d+)", orch)
        workers = int(m.group(1)) if m else 4
        n = inv["F3"]["counts"].get("review/", 0)
        check("A2.F3.partial_upload_visible_and_bounded", 1 <= n <= workers,
              f"review objects after a crash at the first upload={n} (upload workers={workers})")
        if r4_keys := set(_keys(inv["R4"], "review/")) if "R4" in inv else None:
            check("A2.F3.partials_superseded_by_recovery", set(_keys(inv["F3"], "review/")) <= r4_keys,
                  "every partial draft key is rewritten by the recovery run")
    r4, r5 = inv.get("R4"), inv.get("R5")
    if r4:
        written = {k for op, k in r4["r2_writes"] if op in ("upload_file", "put_object") and str(k).startswith("review/")}
        review = set(_keys(r4, "review/"))
        orphans = sorted(review - written)
        check("A2.R4.recovered", r4["exit_code"] == 0 and bool(written), f"exit={r4['exit_code']} drafts written={len(written)}")
        check("A2.R4.no_duplicate_or_orphan_drafts", not orphans,
              f"review objects not (re)written by the recovery run = {orphans[:5]}")
        check("A2.R4.all_sources_marked", sum(1 for k in _keys(r4, "metadata/") if k.startswith("metadata/source_state/"))
              == len(raw0 or {}), "one processed marker per seeded source")
        if raw0 is not None:
            check("A2.R4.raw_unchanged", _keys(r4, "raw/") == raw0, "namespace raw/ identical to the seed")
    if r4 and r5:
        check("A1.R5.no_input", r5["no_input"] and r5["exit_code"] == 0, f"exit={r5['exit_code']} no_input={r5['no_input']}")
        check("A1.R5.no_writes", not r5["r2_writes"], f"r2 writes={len(r5['r2_writes'])}")
        check("A1.R5.namespace_unchanged", r4["objects"] == r5["objects"], "listing identical after the retry")
    # Cycle 12 PA-13 suite (GATE_A_SUITE=pa13): duplicates after a crash + a retry proposing different names
    if "G2" in inv or "L2" in inv:
        def _written_review(x):
            return {k for op, k in x["r2_writes"] if op in ("upload_file", "put_object") and str(k).startswith("review/")}
        marker = ("retry-description", "20991231")
        for leg, crash, retry in (("L", "L1", "L2"), ("G", "G1", "G2")):
            c, r = inv.get(crash), inv.get(retry)
            if not (c and r):
                check(f"PA13.{leg}.ran", False, "phase inventory missing")
                continue
            check(f"PA13.{leg}.crashed_at_first_upload", c["exit_code"] == 97 and c["faults"] == ["after_first_upload"]
                  and c["counts"].get("review/", 0) >= 1, f"exit={c['exit_code']} partial review objects={c['counts'].get('review/', 0)}")
            check(f"PA13.{leg}.retry_completed", r["exit_code"] == 0, f"exit={r['exit_code']}")
            check(f"PA13.{leg}.writes_confined", not c["r2_writes_outside_namespace"] and not r["r2_writes_outside_namespace"],
                  "every write inside the namespace")
        l2, g2 = inv.get("L2"), inv.get("G2")
        if l2:
            review_l = set(_keys(l2, "review/"))
            dup_l = sorted(k for k in review_l if not any(m in k for m in marker))
            check("PA13.L.RED_legacy_duplicates", bool(dup_l) and any(any(m in k for m in marker) for k in review_l),
                  f"legacy names: {len(review_l)} review objects, {len(dup_l)} left over from the crashed run next to the retry's renamed drafts")
        if g2:
            review_g = set(_keys(g2, "review/"))
            ledgers = [k for k in _keys(g2, "metadata/") if k.startswith("metadata/draft_ledger/cr_")]
            check("PA13.G.no_renamed_duplicates", not any(any(m in k for m in marker) for k in review_g),
                  f"no review object carries the retry's description/date ({len(review_g)} objects)")
            # every review object belongs to a ledgered canonical reel (a reel the in-run duplicate filter drops after
            # naming keeps a ledger entry without an object, so ledgers >= objects)
            check("PA13.G.objects_within_canonical_reels", 0 < len(review_g) <= len(ledgers),
                  f"review objects={len(review_g)} canonical reels in the ledger={len(ledgers)}")
            if inv.get("G1"):
                check("PA13.G.partials_kept", set(_keys(inv["G1"], "review/")) <= review_g, "every partial upload of the crashed run is still there (nothing lost)")
            if l2:
                written_l = _written_review(l2)
                check("PA13.G.same_output_count_as_legacy_retry", len(review_g) == len(written_l),
                      f"ledger retry objects={len(review_g)} vs drafts the legacy retry produced={len(written_l)}")
            for seed_name, phase_name in (("seed", "G2"), ("seedL", "L2")):
                if seed_name in inv and phase_name in inv:
                    check(f"PA13.{phase_name}.raw_unchanged", _keys(inv[phase_name], "raw/") == _keys(inv[seed_name], "raw/"),
                          "namespace raw/ identical to the seed")
        g3 = inv.get("G3")
        if g3 and g2:
            check("PA13.G3.retry_after_completion_noop", g3["no_input"] and g3["exit_code"] == 0 and not g3["r2_writes"],
                  f"exit={g3['exit_code']} no_input={g3['no_input']} writes={len(g3['r2_writes'])}")
    compare = d / "production_snapshot_compare.json"
    if compare.exists():
        cmp = json.loads(compare.read_text())
        check("A.production_unchanged", cmp.get("identical") is True, f"differences={len(cmp.get('differences', []))}")
    else:
        check("A.production_unchanged", False, "snapshot compare missing")
    if not any(c["id"].startswith(("A1.", "A2.", "PA13.")) for c in checks):
        check("A.suite_ran", False, "no phase inventories of any suite")
    report = {"pass": all(c["pass"] for c in checks), "checks": checks}
    out.write_text(json.dumps(report, indent=1))
    for c in checks:
        print(("PASS " if c["pass"] else "FAIL ") + c["id"] + " - " + c["detail"])
    print("GATE A", "PASS" if report["pass"] else "FAIL")
    return 0 if report["pass"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("inventory")
    s.add_argument("--run-id", required=True); s.add_argument("--phase", required=True)
    s.add_argument("--exit-code", type=int, default=0); s.add_argument("--tmp", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("evaluate"); s.add_argument("--dir", type=Path, required=True); s.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "inventory":
        return inventory(a.run_id, a.phase, a.exit_code, a.tmp, a.out)
    return evaluate(a.dir, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
