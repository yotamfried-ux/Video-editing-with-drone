"""
scripts/share_drive_folders.py
------------------------------
One-time setup: grant the upload OAuth account editor access to REVIEW and
APPROVED Drive folders so the pipeline can upload drafts.

Auto-detects the email of the OAuth token stored in DRIVE_USER_TOKEN, then
uses the service account (which owns the folders) to create the permission.

Uses the service account (which owns the folders) to create the permissions.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/drive"]

FOLDERS = {
    "REVIEW":   os.environ["REVIEW_FOLDER_ID"],
    "APPROVED": os.environ["APPROVED_FOLDER_ID"],
}


def _get_service_account_service():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"], scopes=_SCOPES
    )
    return build("drive", "v3", credentials=creds)


def _get_upload_email() -> str:
    """Return the email address stored in the OAuth user token."""
    token_file = os.getenv("DRIVE_USER_TOKEN", "drive_user_token.json")
    if not os.path.exists(token_file):
        sys.exit(f"❌ OAuth token file not found: {token_file}")

    creds = Credentials.from_authorized_user_file(token_file, _SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    user_service = build("drive", "v3", credentials=creds)
    about = user_service.about().get(fields="user(emailAddress)").execute()
    return about["user"]["emailAddress"]


def share_folder(service, name: str, folder_id: str, email: str) -> None:
    existing = service.permissions().list(
        fileId=folder_id,
        fields="permissions(id,emailAddress,role)",
    ).execute().get("permissions", [])

    for perm in existing:
        if perm.get("emailAddress", "").lower() == email.lower():
            print(f"  ✅ {name}: {email} already has '{perm['role']}' access")
            return

    service.permissions().create(
        fileId=folder_id,
        body={"type": "user", "role": "writer", "emailAddress": email},
        sendNotificationEmail=False,
        fields="id,role,emailAddress",
    ).execute()
    print(f"  ✅ {name}: granted writer access to {email}")


def main():
    print("🔍 Detecting upload OAuth account email...")
    upload_email = _get_upload_email()
    print(f"   Token belongs to: {upload_email}\n")

    service = _get_service_account_service()
    print(f"Sharing Drive folders with {upload_email}...\n")
    for name, folder_id in FOLDERS.items():
        try:
            share_folder(service, name, folder_id, upload_email)
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            sys.exit(1)
    print("\n✅ Done — pipeline can now upload drafts to REVIEW.")


if __name__ == "__main__":
    main()
