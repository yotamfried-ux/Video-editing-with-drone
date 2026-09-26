#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY") or ""
MARKER = os.environ.get("E2E_MARKER", "")
STATE_PATH = Path(os.environ.get("E2E_OPERATOR_STATE_PATH", "/tmp/operator-app-e2e-state.json"))


def request(method: str, path: str, body=None, prefer: str | None = None):
    if not SUPABASE_URL or not SERVICE_KEY:
        raise SystemExit("SUPABASE_URL and service-role key are required")
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(SUPABASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def load_state():
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def append_env(values: dict[str, str]):
    env_path = os.environ.get("GITHUB_ENV")
    if not env_path:
        return
    with open(env_path, "a", encoding="utf-8") as out:
        for key, value in values.items():
            out.write(f"{key}={value}\n")


def seed():
    if not MARKER:
        raise SystemExit("E2E_MARKER is required")
    compact = "".join(ch for ch in MARKER.lower() if ch.isalnum())[-24:]
    email = f"sportreel.operator.{compact}@example.com"
    password = f"Operator-E2E-{compact}-Aa9!"
    user = request("POST", "/auth/v1/admin/users", {
        "email": email,
        "password": password,
        "email_confirm": True,
    })
    user_id = user["id"]
    support_message = f"operator-support-{MARKER}"
    suggestion_message = f"operator-suggestion-{MARKER}"
    reply = f"operator-reply-{MARKER}"
    sport = f"e2e-{compact}"

    tickets = request(
        "POST",
        "/rest/v1/support_tickets",
        {"user_id": user_id, "message": support_message, "status": "open"},
        "return=representation",
    )
    suggestions = request(
        "POST",
        "/rest/v1/suggestions",
        {"user_id": user_id, "message": suggestion_message},
        "return=representation",
    )
    state = {
        "user_id": user_id,
        "support_id": tickets[0]["id"],
        "suggestion_id": suggestions[0]["id"],
        "support_message": support_message,
        "suggestion_message": suggestion_message,
        "reply": reply,
        "sport": sport,
        "price_ils": 3700,
    }
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    append_env({
        "E2E_SUPPORT_ID": state["support_id"],
        "E2E_SUPPORT_MESSAGE": support_message,
        "E2E_SUGGESTION_MESSAGE": suggestion_message,
        "E2E_OPERATOR_REPLY": reply,
        "E2E_PRICING_SPORT": sport,
    })
    print(json.dumps(state))


def verify():
    s = load_state()
    tickets = request("GET", f"/rest/v1/support_tickets?id=eq.{q(s['support_id'])}&select=id,message,status,operator_reply")
    if len(tickets) != 1:
        raise SystemExit(f"expected one support ticket, got {len(tickets)}")
    ticket = tickets[0]
    if ticket["message"] != s["support_message"] or ticket["status"] != "replied" or ticket["operator_reply"] != s["reply"]:
        raise SystemExit(f"support side effect mismatch: {ticket}")

    suggestions = request("GET", f"/rest/v1/suggestions?id=eq.{q(s['suggestion_id'])}&select=id,message")
    if len(suggestions) != 1 or suggestions[0]["message"] != s["suggestion_message"]:
        raise SystemExit(f"suggestion fixture changed unexpectedly: {suggestions}")

    prices = request("GET", f"/rest/v1/pricing?sport=eq.{q(s['sport'])}&select=sport,price_ils")
    if len(prices) != 1 or int(prices[0]["price_ils"]) != s["price_ils"]:
        raise SystemExit(f"pricing side effect mismatch: {prices}")

    print("PASS operator UI side effects: pricing write + support reply + suggestion read")


def cleanup():
    if not STATE_PATH.exists():
        print("No operator E2E state to clean")
        return
    s = load_state()
    for table, key, value in [
        ("pricing", "sport", s["sport"]),
        ("support_tickets", "id", s["support_id"]),
        ("suggestions", "id", s["suggestion_id"]),
        ("athlete_profiles", "user_id", s["user_id"]),
    ]:
        request("DELETE", f"/rest/v1/{table}?{key}=eq.{q(value)}")
    try:
        request("DELETE", f"/auth/v1/admin/users/{q(s['user_id'])}")
    finally:
        STATE_PATH.unlink(missing_ok=True)
    print("PASS cleaned operator E2E fixtures")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "seed":
        seed()
    elif command == "verify":
        verify()
    elif command == "cleanup":
        cleanup()
    else:
        raise SystemExit("usage: operator_app_e2e_evidence.py seed|verify|cleanup")


if __name__ == "__main__":
    main()
