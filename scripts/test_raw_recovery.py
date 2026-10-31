#!/usr/bin/env python3
"""scripts/raw_recovery.py against a real S3 protocol server (moto): read-only inventory, SHA-proven copy-only plan,
guarded apply. Never touches production."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
BUCKET, PORT = "raw-recovery-test", 5601


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="raw-recovery-")
    os.environ.update({"STORAGE_BACKEND": "r2", "R2_BUCKET": BUCKET, "R2_ENDPOINT_URL": f"http://127.0.0.1:{PORT}",
                       "R2_ACCESS_KEY_ID": "test", "R2_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1",
                       "R2_MAX_ATTEMPTS": "1", "TMP_DIR": tmp})
    from moto.server import ThreadedMotoServer
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    server = ThreadedMotoServer(port=PORT, verbose=False)
    server.start()
    failures: list[str] = []

    def check(name, ok, detail=""):
        print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    try:
        import boto3
        client = boto3.client("s3", endpoint_url=os.environ["R2_ENDPOINT_URL"], aws_access_key_id="test", aws_secret_access_key="test", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        data = {n: (n.encode() * 4000) for n in "ABCDEFGH"}
        sha = {n: hashlib.sha256(b).hexdigest() for n, b in data.items()}

        def put(key, body):
            client.put_object(Bucket=BUCKET, Key=key, Body=body)

        put("raw/A.mp4", data["A"])                         # A: already in raw at its key
        put("raw/flat_B.mp4", data["B"])                    # B: in raw, but not at its recorded (nested) key
        put("processed/C.mp4", data["C"])                   # C: only in processed, SHA matches   -> planned copy
        put("processed/D.mp4", b"X" * len(data["D"]))      # D: only in processed, same size but different bytes -> sha_mismatch
        put("processed/E.mp4", data["E"])                   # E: only in processed, record has no SHA -> unverifiable
        put("review/G.mp4", data["G"])                      # G: only a derived output has this name -> elsewhere (not a source)
        put("processed/H.mp4", data["H"]); put("raw/H.mp4", b"x")  # H: raw/H.mp4 exists with other bytes -> conflict
        rows = []
        def row(n, key, **kw):
            rows.append({"id": f"id-{n}", "status": "verified", "storage_key": key, "verified_size_bytes": len(data[n]),
                         "content_sha256": sha[n], "source_filename": f"{n}.mp4", **kw})
        row("A", "raw/A.mp4"); row("B", "raw/batch_x/flat_B.mp4"); row("C", "raw/C.mp4"); row("D", "raw/D.mp4")
        row("E", "raw/E.mp4", content_sha256=None); row("F", "raw/F.mp4"); row("G", "raw/G.mp4"); row("H", "raw/H.mp4")
        rows.append({"id": "id-Z", "status": "aborted", "storage_key": "raw/Z.mp4", "removed_at": "2026-10-03T00:00:00Z"})
        data["F"] = b"F" * 10  # never uploaded anywhere
        uploads = Path(tmp) / "uploads.json"
        uploads.write_text(json.dumps({"rows": rows}))

        def etags():
            out = {}
            for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
                out.update({o["Key"]: o["ETag"] for o in page.get("Contents", [])})
            return out

        import raw_recovery
        before = etags()
        out = Path(tmp) / "inv.json"
        check("inventory runs", raw_recovery.main(["inventory", "--uploads-json", str(uploads), "--out", str(out)]) == 0)
        rep = json.loads(out.read_text())
        states = {e["upload_id"]: e["state"] for e in rep["entries"]}
        check("A is raw_ok", states["id-A"] == "raw_ok")
        check("B (same bytes elsewhere in raw/) is raw_alt_key, not copied", states["id-B"] == "raw_alt_key")
        check("C is processed_only", states["id-C"] == "processed_only")
        check("E without a durable SHA-256 is unverifiable", states["id-E"] == "unverifiable")
        check("F found nowhere is MISSING (not reconstructed)", states["id-F"] == "missing")
        check("G found only under review/ is 'elsewhere', never treated as the source", states["id-G"] == "elsewhere")
        check("H with a different object at the destination is a conflict", states["id-H"] == "conflict")
        check("aborted records are only counted", rep["aborted_or_removed_records"]["count"] == 1 and "id-Z" not in states)
        check("inventory changed nothing in the bucket", etags() == before)

        plan_file = Path(tmp) / "plan.json"
        raw_recovery.main(["plan", "--uploads-json", str(uploads), "--out", str(plan_file)])
        plan = json.loads(plan_file.read_text())
        states = {e["upload_id"]: e["state"] for e in plan["entries"]}
        check("D with differing bytes is sha_mismatch and not planned", states["id-D"] == "sha_mismatch")
        check("the plan contains exactly one copy: C (processed -> raw)",
              plan["actions"] == [{"action": "copy", "from": "processed/C.mp4", "to": "raw/C.mp4", "size": len(data["C"]), "sha256": sha["C"]}], str(plan["actions"]))
        check("planning changed nothing in the bucket (dry run)", etags() == before)

        for argv, label in [(["apply", "--plan", str(plan_file)], "no confirmation"), (["apply", "--plan", str(plan_file), "--confirm", "yes"], "wrong confirmation")]:
            try:
                raw_recovery.main(argv)
                refused = False
            except SystemExit as exc:
                refused = "nothing was changed" in str(exc)
            check(f"apply refuses with {label}", refused)
        check("refused applies changed nothing", etags() == before)

        tampered = json.loads(plan_file.read_text())
        tampered["actions"].append({"action": "copy", "from": "processed/E.mp4", "to": "raw/E.mp4", "size": 1, "sha256": "0" * 64})
        bad = Path(tmp) / "bad.json"
        bad.write_text(json.dumps(tampered))
        try:
            raw_recovery.main(["apply", "--plan", str(bad), "--confirm", raw_recovery.CONFIRM])
            aborted = False
        except SystemExit:
            aborted = True
        check("a plan with one invalid action aborts BEFORE copying anything (all-or-nothing)", aborted and etags() == before)
        moved = json.loads(plan_file.read_text())
        moved["actions"][0]["to"] = "processed/other.mp4"
        mv = Path(tmp) / "mv.json"
        mv.write_text(json.dumps(moved))
        try:
            raw_recovery.main(["apply", "--plan", str(mv), "--confirm", raw_recovery.CONFIRM])
            aborted = False
        except SystemExit:
            aborted = True
        check("an action that does not target raw/ is refused", aborted and etags() == before)

        res_file = Path(tmp) / "res.json"
        check("apply with the exact confirmation runs", raw_recovery.main(["apply", "--plan", str(plan_file), "--confirm", raw_recovery.CONFIRM, "--out", str(res_file)]) == 0)
        after = etags()
        check("C was COPIED to raw/ with identical bytes", client.get_object(Bucket=BUCKET, Key="raw/C.mp4")["Body"].read() == data["C"])
        check("the processed/ original is kept (copy, not move)", "processed/C.mp4" in after and after["processed/C.mp4"] == before["processed/C.mp4"])
        check("every other object is unchanged and nothing was deleted", {k: v for k, v in after.items() if k != "raw/C.mp4"} == before)
        check("the report states 0 deleted and 0 moved", json.loads(res_file.read_text())["deleted"] == 0 and json.loads(res_file.read_text())["moved"] == 0)
        try:
            raw_recovery.main(["apply", "--plan", str(plan_file), "--confirm", raw_recovery.CONFIRM])
            refused = False
        except SystemExit as exc:
            refused = "refusing to overwrite" in str(exc)
        check("re-applying the same plan refuses (destination exists, never overwritten)", refused and etags() == after)
    finally:
        server.stop()
    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    print("\nPASS raw recovery planner")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
