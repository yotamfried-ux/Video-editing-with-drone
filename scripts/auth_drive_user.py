"""
auth_drive_user.py — הרשאת Google Drive חד-פעמית.
מריץ flow ידני ללא PKCE — מתאים לסביבה ללא דפדפן מקומי.

שימוש: python scripts/auth_drive_user.py
"""

import json, os, secrets, ssl, sys
from urllib.parse import urlencode, urlparse, parse_qs

ssl._create_default_https_context = ssl._create_unverified_context

import requests

CLIENT_SECRET_FILE = os.getenv("OAUTH_CLIENT_SECRET", "oauth_client_secret.json")
TOKEN_FILE         = os.getenv("DRIVE_USER_TOKEN", "drive_user_token.json")

if not os.path.exists(CLIENT_SECRET_FILE):
    print(f"❌ לא נמצא: {CLIENT_SECRET_FILE}")
    sys.exit(1)

with open(CLIENT_SECRET_FILE) as f:
    secret = json.load(f).get("installed") or json.load(open(CLIENT_SECRET_FILE)).get("web")

CLIENT_ID     = secret["client_id"]
CLIENT_SECRET = secret["client_secret"]
REDIRECT_URI  = "urn:ietf:wg:oauth:2.0:oob"   # no-localhost OOB — code shown on page
SCOPES        = "https://www.googleapis.com/auth/drive"

# ── 1. Build auth URL ──────────────────────────────────────────────────────

params = {
    "client_id":     CLIENT_ID,
    "redirect_uri":  REDIRECT_URI,
    "response_type": "code",
    "scope":         SCOPES,
    "state":         secrets.token_urlsafe(8),
    "access_type":   "offline",
    "prompt":        "consent",
}
auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

print()
print("=" * 64)
print("שלב 1 — פתח את הקישור הבא בדפדפן (בטלפון):")
print()
print(auth_url)
print()
print("שלב 2 — התחבר עם d2r.yotam@gmail.com ואשר גישה.")
print("שלב 3 — העתק את הקוד שיופיע על המסך ושלח אותו בצ'אט.")
print("=" * 64)
print()

code = input("הדבק את הקוד כאן: ").strip()

# ── 2. Exchange code for tokens ────────────────────────────────────────────

resp = requests.post("https://oauth2.googleapis.com/token", data={
    "code":          code,
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri":  REDIRECT_URI,
    "grant_type":    "authorization_code",
}, verify=False)

if not resp.ok:
    print(f"❌ Token exchange failed: {resp.text}")
    sys.exit(1)

token = resp.json()

# ── 3. Save in google.oauth2.credentials format ────────────────────────────

cred_data = {
    "token":         token.get("access_token"),
    "refresh_token": token.get("refresh_token"),
    "token_uri":     "https://oauth2.googleapis.com/token",
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "scopes":        [SCOPES],
}
with open(TOKEN_FILE, "w") as f:
    json.dump(cred_data, f, indent=2)

print(f"\n✅ Token saved to {TOKEN_FILE}")
print("   הפייפליין מוכן להעלות קבצים בשם d2r.yotam@gmail.com")
