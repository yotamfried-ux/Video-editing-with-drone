"""
setup_drive.py — One-time setup script.
יוצר את שלוש תיקיות ה-Drive הנדרשות ומדפיס את ה-IDs לשים ב-.env.
הרץ פעם אחת: python setup_drive.py
"""

import ssl
import os

# bypass self-signed cert in this environment (one-time setup script only)
ssl._create_default_https_context = ssl._create_unverified_context
os.environ.setdefault("PYTHONHTTPSVERIFY", "0")

import httplib2  # noqa: E402 — must patch before google-auth uses it
_orig_http_init = httplib2.Http.__init__
def _http_init_no_verify(self, *args, **kwargs):
    kwargs.setdefault("disable_ssl_certificate_validation", True)
    _orig_http_init(self, *args, **kwargs)
httplib2.Http.__init__ = _http_init_no_verify

from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
_SCOPES = ["https://www.googleapis.com/auth/drive"]

FOLDERS = [
    ("D-to-R RAW Drone Footage",       "RAW_FOLDER_ID"),
    ("D-to-R Review Drafts",           "REVIEW_FOLDER_ID"),
    ("D-to-R Approved Reels",          "APPROVED_FOLDER_ID"),
    ("D-to-R Previews",                "PREVIEW_FOLDER_ID"),
    ("D-to-R Pending Payment",         "PENDING_PAYMENT_FOLDER_ID"),
    ("D-to-R Processed Originals",     "PROCESSED_FOLDER_ID"),
    ("D-to-R Highlight Clips",         "CLIPS_FOLDER_ID"),
]


def create_folder(service, name: str) -> str:
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    result = service.files().create(body=metadata, fields="id, webViewLink").execute()
    return result["id"], result.get("webViewLink", "")


def main():
    print("📁 Setting up Google Drive folders for D to R pipeline...\n")

    creds = service_account.Credentials.from_service_account_file(
        _SERVICE_ACCOUNT_JSON, scopes=_SCOPES
    )
    service = build("drive", "v3", credentials=creds)

    env_lines = []
    for folder_name, env_key in FOLDERS:
        folder_id, link = create_folder(service, folder_name)
        print(f"✅ Created: {folder_name}")
        print(f"   ID:  {folder_id}")
        print(f"   URL: {link}")
        print()
        env_lines.append(f"{env_key}={folder_id}")

    print("─" * 50)
    print("📋 Add these lines to your .env file:\n")
    for line in env_lines:
        print(f"  {line}")
    print()
    print("⚠️  Also share each folder with your service account email:")
    try:
        sa_info = __import__("json").load(open(_SERVICE_ACCOUNT_JSON))
        print(f"   → {sa_info['client_email']}")
    except Exception:
        print("   (see client_email in your service_account.json)")


if __name__ == "__main__":
    main()
