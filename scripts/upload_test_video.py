"""
upload_test_video.py — העלה סרטון מקומי לתיקיית RAW ב-Drive.
שימוש: python scripts/upload_test_video.py /path/to/video.mp4
"""
import ssl, os, sys

ssl._create_default_https_context = ssl._create_unverified_context
import httplib2
_orig = httplib2.Http.__init__
def _no_verify(self, *a, **kw):
    kw.setdefault("disable_ssl_certificate_validation", True)
    _orig(self, *a, **kw)
httplib2.Http.__init__ = _no_verify

from dotenv import load_dotenv
load_dotenv()
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

if len(sys.argv) < 2:
    print("Usage: python scripts/upload_test_video.py /path/to/video.mp4")
    sys.exit(1)

video_path = sys.argv[1]
if not os.path.exists(video_path):
    print(f"❌ File not found: {video_path}")
    sys.exit(1)

creds = service_account.Credentials.from_service_account_file(
    os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"],
    scopes=["https://www.googleapis.com/auth/drive"]
)
svc = build("drive", "v3", credentials=creds)

filename = os.path.basename(video_path)
file_size = os.path.getsize(video_path)
print(f"📤 Uploading '{filename}' ({file_size / 1024 / 1024:.1f} MB) to RAW folder...")

media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=5*1024*1024)
meta  = {"name": filename, "parents": [os.environ["RAW_FOLDER_ID"]]}
req   = svc.files().create(body=meta, media_body=media, fields="id, webViewLink")

response = None
while response is None:
    status, response = req.next_chunk()
    if status:
        print(f"  ... {int(status.progress() * 100)}%", end="\r")

print(f"\n✅ Uploaded! File ID: {response['id']}")
print(f"   URL: {response.get('webViewLink', '')}")
print(f"\nעכשיו הרץ: python run.py")
