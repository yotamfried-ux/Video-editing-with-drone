"""
scripts/share_drive_folders.py
------------------------------
One-time setup: grant d2r.yotam@gmail.com editor access to REVIEW and APPROVED
Drive folders so the pipeline can upload drafts on behalf of that account.

Uses the service account (which owns the folders) to create the permissions.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from google.oauth2 import service_account
from googleapiclient.discovery import build

_SCOPES = ["https://www.googleapis.com/auth/drive"]
UPLOAD_EMAIL = "d2r.yotam@gmail.com"

FOLDERS = {
    "REVIEW":   os.environ["REVIEW_FOLDER_ID"],
    "APPROVED": os.environ["APPROVED_FOLDER_ID"],
}


def _get_service():
    creds = service_account.Credentials.from_service_account_file(
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"], scopes=_SCOPES
    )
    return build("drive", "v3", credentials=creds)


def share_folder(service, name: str, folder_id: str) -> None:
    # Check existing permissions first
    existing = service.permissions().list(
        fileId=folder_id,
        fields="permissions(id,emailAddress,role)",
    ).execute().get("permissions", [])

    for perm in existing:
        if perm.get("emailAddress", "").lower() == UPLOAD_EMAIL.lower():
            print(f"  ✅ {name}: {UPLOAD_EMAIL} already has '{perm['role']}' access")
            return

    service.permissions().create(
        fileId=folder_id,
        body={
            "type": "user",
            "role": "writer",
            "emailAddress": UPLOAD_EMAIL,
        },
        sendNotificationEmail=False,
        fields="id,role,emailAddress",
    ).execute()
    print(f"  ✅ {name}: granted writer access to {UPLOAD_EMAIL}")


def main():
    service = _get_service()
    print(f"Sharing Drive folders with {UPLOAD_EMAIL}...\n")
    for name, folder_id in FOLDERS.items():
        try:
            share_folder(service, name, folder_id)
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            sys.exit(1)
    print("\n✅ Done — pipeline can now upload drafts to REVIEW.")


if __name__ == "__main__":
    main()
