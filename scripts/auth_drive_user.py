"""
auth_drive_user.py — הרץ פעם אחת כדי לאשר גישה ל-Drive בשם המשתמש.
יוצר drive_user_token.json שישמש להעלאות (במקום הסרוויס אקאונט).

שלבים:
1. כנס ל: https://console.cloud.google.com/apis/credentials
2. צור OAuth 2.0 Client ID (סוג: Desktop app)
3. הורד את ה-JSON ושמור אותו כ: oauth_client_secret.json
4. הרץ: python scripts/auth_drive_user.py
"""

import ssl, os, json, sys

ssl._create_default_https_context = ssl._create_unverified_context

CLIENT_SECRET_FILE = os.getenv("OAUTH_CLIENT_SECRET", "oauth_client_secret.json")
TOKEN_FILE         = os.getenv("DRIVE_USER_TOKEN", "drive_user_token.json")
SCOPES             = ["https://www.googleapis.com/auth/drive"]

if not os.path.exists(CLIENT_SECRET_FILE):
    print(f"❌ לא נמצא קובץ: {CLIENT_SECRET_FILE}")
    print()
    print("צעדים ליצירתו:")
    print("  1. כנס ל: https://console.cloud.google.com/apis/credentials")
    print("  2. לחץ 'Create credentials' → 'OAuth 2.0 Client IDs'")
    print("  3. בחר 'Desktop app', תן שם, לחץ Create")
    print("  4. לחץ 'Download JSON' ושמור בשם: oauth_client_secret.json")
    sys.exit(1)

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

creds = None
if os.path.exists(TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        # Use console flow (no browser needed on server)
        creds = flow.run_console()

with open(TOKEN_FILE, "w") as f:
    f.write(creds.to_json())

print(f"✅ Token saved to {TOKEN_FILE}")
print(f"   המשתמש מורשה — העלאות יתבצעו בשם {creds.token_uri}")
