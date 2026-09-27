#!/usr/bin/env python3
import argparse, json, os, time
from datetime import date, datetime, timezone
from pathlib import Path

import boto3
import requests
from supabase import create_client

API_BASE = os.environ.get("API_BASE", "https://video-editing-with-drone.vercel.app").rstrip("/")
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
R2_BUCKET = os.environ.get("R2_BUCKET", "sportreel")
STATE = Path(os.environ["E2E_REVIEW_STATE_PATH"])
EVIDENCE = Path(os.environ["E2E_REVIEW_EVIDENCE_PATH"])
MARKER = os.environ["E2E_REVIEW_MARKER"]
FIXTURE = Path(os.environ["E2E_REVIEW_FIXTURE_MP4"])
REPO = os.environ["GITHUB_REPOSITORY"]
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

def r2():
    endpoint = os.environ.get("R2_ENDPOINT_URL", "").strip()
    if not endpoint:
        endpoint = f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )

def gh_headers():
    return {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"}

def list_workflow_runs(workflow):
    if not GH_TOKEN:
        return []
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/runs"
    r = requests.get(url, headers=gh_headers(), params={"per_page": 50}, timeout=20)
    r.raise_for_status()
    return [int(x["id"]) for x in r.json().get("workflow_runs", [])]

def write_state(data):
    STATE.write_text(json.dumps(data, indent=2))

def read_state():
    return json.loads(STATE.read_text())

def emit_env(data):
    env_path = os.environ.get("GITHUB_ENV")
    if not env_path:
        return
    with open(env_path, "a", encoding="utf-8") as out:
        for k, v in data.items():
            out.write(f"{k}={v}\n")

def safe_id(prefix, name):
    return prefix + "-" + "".join(c if c.isalnum() or c in "_-" else "_" for c in name)

def seed():
    today = date.today().isoformat()
    blocked_name = f"E2E_QUAL_BLOCKED_{MARKER}_{today}_part_1.mp4"
    ready_name = f"E2E_QUAL_PASS_{MARKER}_{today}_part_1.mp4"
    blocked_key = f"review/{blocked_name}"
    ready_key = f"review/{ready_name}"
    cli = r2()
    body = FIXTURE.read_bytes()
    for key in (blocked_key, ready_key):
        cli.put_object(Bucket=R2_BUCKET, Key=key, Body=body, ContentType="video/mp4")

    blocked_pub = {
        "storage_object_id": blocked_key,
        "draft_name": blocked_name,
        "pipeline_run_id": None,
        "athlete_key": f"e2e-blocked-{MARKER}",
        "part_index": 1,
        "publishable": False,
        "qa_evidence_recorded": True,
        "qa_verdict": "FAIL",
        "qa_passed": False,
        "technical_issues": ["E2E qualification QA defect"],
        "approval_blocked_reasons": ["E2E qualification requires re-edit"],
        "media_specs_revision": "e2e",
        "manifest_revision": f"e2e-{MARKER}",
    }
    ready_pub = {
        "storage_object_id": ready_key,
        "draft_name": ready_name,
        "pipeline_run_id": None,
        "athlete_key": f"e2e-ready-{MARKER}",
        "part_index": 1,
        "publishable": True,
        "qa_evidence_recorded": True,
        "qa_verdict": "PASS",
        "qa_passed": True,
        "technical_issues": [],
        "approval_blocked_reasons": [],
        "media_specs_revision": "e2e",
        "manifest_revision": f"e2e-{MARKER}",
    }
    sb.table("draft_publishability").upsert([blocked_pub, ready_pub]).execute()
    req = sb.table("reprocess_requests").insert({
        "draft_name": blocked_name,
        "notes": "E2E qualification blocked QA notes",
        "status": "qa_blocked",
        "origin": "qa_gate",
        "qa_defects": [{"type": "E2E_QUAL", "blocking": True, "note": "qualification fixture"}],
        "approval_blocked_reasons": ["E2E qualification requires re-edit"],
        "attempt_count": 0,
        "max_attempts": 3,
    }).execute().data[0]
    state = {
        "marker": MARKER,
        "blocked_name": blocked_name,
        "blocked_key": blocked_key,
        "blocked_request_id": req["id"],
        "ready_name": ready_name,
        "ready_key": ready_key,
        "seeded_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_baseline": list_workflow_runs("pipeline-run.yml"),
        "delivery_baseline": list_workflow_runs("deliver.yml"),
    }
    write_state(state)
    emit_env({
        "BLOCKED_REEDIT_ID": safe_id("review-reedit", blocked_name),
        "READY_APPROVE_ID": safe_id("review-approve", ready_name),
        "BLOCKED_NAME": blocked_name,
        "READY_NAME": ready_name,
    })
    EVIDENCE.write_text(json.dumps({"seed": state}, indent=2))

def wait_for_reedit_and_cancel():
    state = read_state()
    deadline = time.time() + 180
    row = None
    run_row = None
    while time.time() < deadline:
        rows = sb.table("reprocess_requests").select("*").eq("id", state["blocked_request_id"]).execute().data
        if rows and rows[0].get("last_pipeline_run_id"):
            row = rows[0]
            rr = sb.table("pipeline_runs").select("*").eq("id", row["last_pipeline_run_id"]).execute().data
            if rr:
                run_row = rr[0]
                break
        time.sleep(3)
    if not row or not run_row:
        raise RuntimeError("re-edit durable rows were not created")
    if row.get("status") not in ("pending", "queued"):
        raise RuntimeError(f"unexpected re-edit status: {row.get('status')}")
    if int(row.get("attempt_count") or 0) < 1:
        raise RuntimeError("re-edit attempt count did not increment")

    current = list_workflow_runs("pipeline-run.yml")
    new_runs = [x for x in current if x not in set(state["pipeline_baseline"])]
    if len(new_runs) != 1:
        raise RuntimeError(f"expected exactly one new pipeline workflow run, found {new_runs}")
    rid = new_runs[0]
    resp = requests.post(
        f"https://api.github.com/repos/{REPO}/actions/runs/{rid}/cancel",
        headers=gh_headers(), timeout=20
    )
    if resp.status_code not in (202, 409):
        raise RuntimeError(f"pipeline cancel failed: {resp.status_code} {resp.text[:200]}")
    state["pipeline_run_db_id"] = run_row["id"]
    state["pipeline_actions_run_id"] = rid
    write_state(state)
    evidence = json.loads(EVIDENCE.read_text())
    evidence["reedit"] = {"request": row, "pipeline_run": run_row, "actions_run_id": rid, "cancel_status": resp.status_code}
    EVIDENCE.write_text(json.dumps(evidence, indent=2, default=str))

def wait_for_approval_and_cancel_delivery():
    state = read_state()
    deadline = time.time() + 180
    delivery = None
    while time.time() < deadline:
        rows = (sb.table("delivery_runs").select("*")
                .eq("approved_file_name", state["ready_name"])
                .order("approved_at", desc=True).limit(1).execute().data)
        if rows:
            delivery = rows[0]
            break
        time.sleep(3)
    if not delivery:
        raise RuntimeError("approval did not create delivery_run")

    cli = r2()
    try:
        cli.head_object(Bucket=R2_BUCKET, Key=f"approved/{state['ready_name']}")
    except Exception as exc:
        raise RuntimeError("approval did not move review object to approved/") from exc
    try:
        cli.head_object(Bucket=R2_BUCKET, Key=state["ready_key"])
        raise RuntimeError("review object still exists after approval")
    except RuntimeError:
        raise
    except Exception:
        pass

    current = list_workflow_runs("deliver.yml")
    new_runs = [x for x in current if x not in set(state["delivery_baseline"])]
    if len(new_runs) != 1:
        raise RuntimeError(f"expected exactly one new delivery workflow run, found {new_runs}")
    rid = new_runs[0]
    resp = requests.post(
        f"https://api.github.com/repos/{REPO}/actions/runs/{rid}/cancel",
        headers=gh_headers(), timeout=20
    )
    if resp.status_code not in (202, 409):
        raise RuntimeError(f"delivery cancel failed: {resp.status_code} {resp.text[:200]}")
    state["delivery_run_id"] = delivery["id"]
    state["delivery_actions_run_id"] = rid
    write_state(state)
    evidence = json.loads(EVIDENCE.read_text())
    evidence["approval"] = {"delivery_run": delivery, "actions_run_id": rid, "cancel_status": resp.status_code}
    EVIDENCE.write_text(json.dumps(evidence, indent=2, default=str))

def seed_discover_output():
    state = read_state()
    preview_path = f"{date.today().isoformat()}/{MARKER}_preview.mp4"
    bucket = sb.storage.from_("reels")
    with open(FIXTURE, "rb") as fh:
        bucket.upload(preview_path, fh, file_options={"content-type": "video/mp4"})
    reel = sb.table("reels").insert({
        "sport": f"e2e-{MARKER[-8:]}",
        "athlete_desc": f"E2E Discover {MARKER}",
        "recording_date": date.today().isoformat(),
        "storage_path": preview_path,
        "source_video": state["ready_name"],
        "status": "published",
    }).execute().data[0]
    sb.table("delivery_runs").update({
        "status": "succeeded",
        "stage": "finished",
        "discover_reel_id": reel["id"],
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", state["delivery_run_id"]).execute()
    state["reel_id"] = reel["id"]
    state["reel_token"] = reel.get("token")
    state["reel_storage_path"] = preview_path
    state["discover_sport"] = f"e2e-{MARKER[-8:]}"
    write_state(state)
    emit_env({"DISCOVER_SPORT": state["discover_sport"]})
    evidence = json.loads(EVIDENCE.read_text())
    evidence["discover_seed"] = {"reel": reel}
    EVIDENCE.write_text(json.dumps(evidence, indent=2, default=str))

def verify_discover():
    state = read_state()
    rows = sb.table("reels").select("*").eq("id", state["reel_id"]).execute().data
    if len(rows) != 1 or rows[0].get("status") != "published":
        raise RuntimeError(f"Discover reel evidence mismatch: {rows}")
    delivery = sb.table("delivery_runs").select("*").eq("id", state["delivery_run_id"]).execute().data
    if len(delivery) != 1 or delivery[0].get("discover_reel_id") != state["reel_id"]:
        raise RuntimeError(f"delivery linkage mismatch: {delivery}")
    evidence = json.loads(EVIDENCE.read_text())
    evidence["discover_verify"] = {"reel": rows[0], "delivery": delivery[0]}
    EVIDENCE.write_text(json.dumps(evidence, indent=2, default=str))

def cleanup():
    if not STATE.exists():
        return
    state = read_state()
    cli = r2()
    names = [state.get("blocked_name"), state.get("ready_name")]
    for name in filter(None, names):
        for prefix in ("review/", "approved/", "pending_payment/", "processed/"):
            try:
                cli.delete_object(Bucket=R2_BUCKET, Key=f"{prefix}{name}")
            except Exception:
                pass
        try:
            cli.delete_object(Bucket=R2_BUCKET, Key=f"previews/{name.replace('.mp4','_preview.mp4')}")
        except Exception:
            pass
    if state.get("reel_storage_path"):
        try:
            sb.storage.from_("reels").remove([state["reel_storage_path"]])
        except Exception:
            pass
    for table, col, values in [
        ("reprocess_requests", "draft_name", names),
        ("draft_publishability", "draft_name", names),
        ("drafts", "draft_name", names),
    ]:
        for value in filter(None, values):
            try:
                sb.table(table).delete().eq(col, value).execute()
            except Exception:
                pass
    if state.get("reel_id"):
        try: sb.table("reels").delete().eq("id", state["reel_id"]).execute()
        except Exception: pass
    if state.get("delivery_run_id"):
        try: sb.table("delivery_runs").delete().eq("id", state["delivery_run_id"]).execute()
        except Exception: pass
    if state.get("pipeline_run_db_id"):
        try: sb.table("pipeline_runs").delete().eq("id", state["pipeline_run_db_id"]).execute()
        except Exception: pass

def main():
    p=argparse.ArgumentParser()
    p.add_argument("command", choices=["seed","verify-reedit-cancel","verify-approval-cancel","seed-discover","verify-discover","cleanup"])
    args=p.parse_args()
    {
        "seed": seed,
        "verify-reedit-cancel": wait_for_reedit_and_cancel,
        "verify-approval-cancel": wait_for_approval_and_cancel_delivery,
        "seed-discover": seed_discover_output,
        "verify-discover": verify_discover,
        "cleanup": cleanup,
    }[args.command]()

if __name__ == "__main__":
    main()
