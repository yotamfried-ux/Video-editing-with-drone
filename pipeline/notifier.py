"""
pipeline/notifier.py — Gmail delivery via Google service account.
שולח ללקוח אימייל HTML עם קישורים לקליפים המוכנים.
"""

import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2 import service_account
from googleapiclient.discovery import build

import config

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

_SPORT_EMOJI = {
    "surfing": "🏄",
    "football": "🏈",
    "other": "🎬",
    "unknown": "🎬",
}


def _get_gmail_service(sender_email: str):
    """
    Build Gmail API service using service account with domain-wide delegation.
    The service account must be granted the gmail.send scope in Google Workspace admin.
    """
    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=_SCOPES,
    )
    # Impersonate the sender so the email appears to come from a real address
    delegated_creds = creds.with_subject(sender_email)
    return build("gmail", "v1", credentials=delegated_creds)


def _build_html(
    clips_links: list[str],
    sport_type: str,
    video_name: str,
) -> str:
    emoji = _SPORT_EMOJI.get(sport_type, "🎬")
    clip_rows = ""
    for i, link in enumerate(clips_links, start=1):
        clip_rows += f"""
        <tr>
          <td style="padding:8px 0;">
            <a href="{link}" style="
              display:inline-block;
              padding:10px 22px;
              background:#1a1a2e;
              color:#e0e0ff;
              text-decoration:none;
              border-radius:6px;
              font-weight:600;
              font-size:14px;
            ">▶ Clip {i}</a>
          </td>
        </tr>"""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:30px;">
  <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:10px;overflow:hidden;margin:0 auto;">
    <tr>
      <td style="background:#1a1a2e;padding:24px 32px;">
        <h1 style="color:#fff;margin:0;font-size:22px;">{emoji} D to R — Highlight Clips Ready</h1>
      </td>
    </tr>
    <tr>
      <td style="padding:28px 32px;">
        <p style="font-size:15px;color:#333;">
          Your drone footage has been processed!<br>
          <strong>{len(clips_links)} highlight clip(s)</strong> were extracted from
          <em>{video_name}</em>.
        </p>
        <p style="font-size:13px;color:#666;margin-bottom:20px;">
          Sport detected: <strong>{sport_type.capitalize()}</strong>
        </p>
        <table cellpadding="0" cellspacing="0">
          {clip_rows}
        </table>
        <hr style="border:none;border-top:1px solid #eee;margin:28px 0;">
        <p style="font-size:12px;color:#999;">
          Delivered automatically by the D to R pipeline.<br>
          Clips are stored in your Google Drive CLIPS folder.
        </p>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def send_summary_email(
    client_email: str,
    clips_links: list[str],
    sport_type: str,
    video_name: str,
) -> None:
    """
    Send an HTML summary email to client_email with links to all processed clips.

    Args:
        client_email: Recipient email address.
        clips_links:  List of Google Drive shareable links.
        sport_type:   "surfing", "football", or "other".
        video_name:   Original video filename (shown in subject line).
    """
    emoji = _SPORT_EMOJI.get(sport_type, "🎬")
    subject = f"{emoji} Your {sport_type.capitalize()} Highlights Are Ready — {video_name}"

    print(f"📧 Sending summary email to {client_email} ({len(clips_links)} clip link(s))...")

    try:
        # Use NOTIFY_EMAIL as the sender (must be authorised for delegation)
        sender = config.NOTIFY_EMAIL
        service = _get_gmail_service(sender)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = client_email

        html_body = _build_html(clips_links, sport_type, video_name)
        msg.attach(MIMEText(html_body, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()

        print(f"✅ Email sent to {client_email}")
        logger.info("Email sent to %s for video '%s' (%d clips)", client_email, video_name, len(clips_links))

    except Exception as e:
        logger.error("❌ Failed to send email to %s: %s", client_email, e)
        print(f"❌ Email delivery failed: {e}")
