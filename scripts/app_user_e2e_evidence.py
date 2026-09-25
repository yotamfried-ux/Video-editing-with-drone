#!/usr/bin/env python3
"""Authoritative backend fixture/evidence for the Android user-journey E2E.

Uses a service-role key only inside CI. The Android app itself still signs in
with the public client and exercises normal RLS-protected paths.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY", "")
PUBLISHABLE = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
STATE = Path(os.environ.get("E2E_STATE_PATH", "/tmp/sportreel-user-e2e.json"))


def request(method: str, path: str, *, key: str, token: str | None = None,
            body: object | None = None, extra: dict[str, str] | None = None) -> tuple[int, object | None]:
    if not BASE:
        raise RuntimeError("SUPABASE_URL is required")
    headers = {"apikey": key, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif key:
        headers["Authorization"] = f"Bearer {key}"
    if extra:
        headers.update(extra)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload


def require_service() -> None:
    if not SERVICE:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY/SUPABASE_SERVICE_KEY is required")


def service_rows(table: str, query: str) -> list[dict]:
    status, payload = request("GET", f"/rest/v1/{table}?{query}", key=SERVICE)
    if status != 200 or not isinstance(payload, list):
        raise RuntimeError(f"{table} query failed ({status}): {payload}")
    return payload


def service_delete(table: str, query: str) -> None:
    status, payload = request("DELETE", f"/rest/v1/{table}?{query}", key=SERVICE,
                              extra={"Prefer": "return=minimal"})
    if status not in (200, 204):
        raise RuntimeError(f"{table} cleanup failed ({status}): {payload}")


def service_patch(table: str, query: str, body: dict) -> list[dict]:
    status, payload = request("PATCH", f"/rest/v1/{table}?{query}", key=SERVICE, body=body,
                              extra={"Prefer": "return=representation"})
    if status != 200 or not isinstance(payload, list):
        raise RuntimeError(f"{table} patch failed ({status}): {payload}")
    return payload


def create_user(email: str, password: str) -> str:
    status, payload = request(
        "POST", "/auth/v1/admin/users", key=SERVICE,
        body={"email": email, "password": password, "email_confirm": True},
    )
    if status not in (200, 201) or not isinstance(payload, dict) or not payload.get("id"):
        raise RuntimeError(f"admin create user failed ({status}): {payload}")
    return str(payload["id"])


def delete_user(user_id: str) -> None:
    status, payload = request("DELETE", f"/auth/v1/admin/users/{user_id}", key=SERVICE)
    if status not in (200, 204):
        raise RuntimeError(f"admin delete user failed ({status}): {payload}")


def wait_for_profile(user_id: str) -> None:
    q = urllib.parse.urlencode({"user_id": f"eq.{user_id}", "select": "user_id,name,email"})
    for _ in range(30):
        rows = service_rows("athlete_profiles", q)
        if rows:
            return
        time.sleep(1)
    raise RuntimeError("athlete profile trigger did not create a row")


def sign_in(email: str, password: str) -> str:
    if not PUBLISHABLE:
        raise RuntimeError("SUPABASE_PUBLISHABLE_KEY is required for RLS verification")
    status, payload = request(
        "POST", "/auth/v1/token?grant_type=password", key=PUBLISHABLE,
        body={"email": email, "password": password},
    )
    if status != 200 or not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError(f"test-user sign in failed ({status}): {payload}")
    return str(payload["access_token"])


def user_rows(table: str, query: str, token: str) -> list[dict]:
    status, payload = request("GET", f"/rest/v1/{table}?{query}", key=PUBLISHABLE, token=token)
    if status != 200 or not isinstance(payload, list):
        raise RuntimeError(f"user {table} query failed ({status}): {payload}")
    return payload


def seed(args: argparse.Namespace) -> None:
    require_service()
    primary_id = create_user(args.email, args.password)
    secondary_id = create_user(args.other_email, args.other_password)
    wait_for_profile(primary_id)
    wait_for_profile(secondary_id)
    service_patch(
        "athlete_profiles",
        urllib.parse.urlencode({"user_id": f"eq.{primary_id}"}),
        {"name": f"E2E Seed {args.marker}"},
    )
    service_patch(
        "athlete_profiles",
        urllib.parse.urlencode({"user_id": f"eq.{secondary_id}"}),
        {"name": f"E2E Other {args.marker}"},
    )
    STATE.write_text(json.dumps({
        "marker": args.marker,
        "primary_id": primary_id,
        "secondary_id": secondary_id,
        "email": args.email,
        "password": args.password,
        "other_email": args.other_email,
        "other_password": args.other_password,
    }))
    print("PASS seeded two isolated confirmed test users")


def verify(args: argparse.Namespace) -> None:
    require_service()
    state = json.loads(STATE.read_text())
    marker = state["marker"]
    primary = state["primary_id"]
    expected_name = f"E2E Android {marker}"
    support_send = f"support-send-{marker}"
    support_cancel = f"support-cancel-{marker}"
    suggestion_send = f"suggestion-send-{marker}"
    suggestion_cancel = f"suggestion-cancel-{marker}"

    qp = urllib.parse.urlencode({"user_id": f"eq.{primary}", "select": "user_id,name,email"})
    profiles = service_rows("athlete_profiles", qp)
    if len(profiles) != 1 or profiles[0].get("name") != expected_name:
        raise RuntimeError(f"profile evidence mismatch: {profiles}")

    def by_message(table: str, message: str) -> list[dict]:
        q = urllib.parse.urlencode({
            "user_id": f"eq.{primary}",
            "message": f"eq.{message}",
            "select": "id,user_id,message",
        })
        return service_rows(table, q)

    if len(by_message("support_tickets", support_send)) != 1:
        raise RuntimeError("support Send Message did not create exactly one row")
    if by_message("support_tickets", support_cancel):
        raise RuntimeError("support Cancel unexpectedly created a row")
    if len(by_message("suggestions", suggestion_send)) != 1:
        raise RuntimeError("Send Suggestion did not create exactly one row")
    if by_message("suggestions", suggestion_cancel):
        raise RuntimeError("suggestion Cancel unexpectedly created a row")

    primary_token = sign_in(state["email"], state["password"])
    own_q = urllib.parse.urlencode({"message": f"eq.{support_send}", "select": "id,user_id,message"})
    if len(user_rows("support_tickets", own_q, primary_token)) != 1:
        raise RuntimeError("primary user cannot read own support ticket through RLS")

    other_token = sign_in(state["other_email"], state["other_password"])
    cross_q = urllib.parse.urlencode({
        "user_id": f"eq.{primary}", "select": "id,user_id,message"
    })
    if user_rows("support_tickets", cross_q, other_token):
        raise RuntimeError("RLS leak: second user can read primary user's support ticket")

    patch_path = "/rest/v1/athlete_profiles?" + urllib.parse.urlencode({"user_id": f"eq.{primary}"})
    status, payload = request(
        "PATCH", patch_path, key=PUBLISHABLE, token=other_token,
        body={"name": "E2E RLS SHOULD NOT WRITE"},
        extra={"Prefer": "return=representation"},
    )
    if status not in (200, 204):
        raise RuntimeError(f"cross-user profile update returned unexpected status {status}: {payload}")
    if isinstance(payload, list) and payload:
        raise RuntimeError("RLS leak: second user updated primary user's profile")
    profiles_after = service_rows("athlete_profiles", qp)
    if profiles_after[0].get("name") != expected_name:
        raise RuntimeError("RLS leak: primary profile changed after cross-user update attempt")

    print("PASS Android user journey backend evidence + cross-user RLS isolation")


def cleanup(_: argparse.Namespace) -> None:
    if not STATE.exists():
        print("INFO no E2E state file; nothing to clean")
        return
    require_service()
    state = json.loads(STATE.read_text())
    for uid in (state.get("primary_id"), state.get("secondary_id")):
        if not uid:
            continue
        encoded = urllib.parse.urlencode({"user_id": f"eq.{uid}"})
        for table in ("support_tickets", "suggestions", "push_tokens", "athlete_profiles"):
            try:
                service_delete(table, encoded)
            except Exception as exc:
                print(f"WARN cleanup {table}: {exc}")
        try:
            delete_user(uid)
        except Exception as exc:
            print(f"WARN cleanup auth user: {exc}")
    STATE.unlink(missing_ok=True)
    print("PASS cleaned Android E2E test users/data")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("seed")
    for name in ("marker", "email", "password", "other_email", "other_password"):
        s.add_argument(f"--{name.replace('_', '-')}", required=True)
    sub.add_parser("verify")
    sub.add_parser("cleanup")
    return p


def main() -> int:
    args = parser().parse_args()
    {"seed": seed, "verify": verify, "cleanup": cleanup}[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
