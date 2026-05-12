"""
pipeline/notifier.py — Gmail delivery via Google service account.
שולח אימייל HTML לבעל הפייפליין ולמצולם (אם נמצא ב-clients.json).
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
    "surfing":  "🏄",
    "football": "🏈",
    "mixed":    "🎬",
    "other":    "🎬",
    "unknown":  "🎬",
}


def _get_gmail_service(sender_email: str):
    """
    Build Gmail API service using service account with domain-wide delegation.
    The service account must have gmail.send scope granted in Google Workspace admin.
    """
    creds = service_account.Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=_SCOPES,
    )
    delegated_creds = creds.with_subject(sender_email)
    return build("gmail", "v1", credentials=delegated_creds)


def _build_html(
    clips_links: list[str],
    sport_type: str,
    video_name: str,
    is_owner: bool,
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

    owner_note = ""
    if is_owner:
        owner_note = """
        <p style="font-size:12px;background:#f0f4ff;border-left:3px solid #4466cc;
                  padding:10px 14px;border-radius:4px;color:#334;">
          🔧 <strong>Owner summary</strong> — you are receiving this as the pipeline operator.
          Clips are archived in your Google Drive PROCESSED folder.
        </p>"""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:30px;">
  <table width="600" cellpadding="0" cellspacing="0"
         style="background:#fff;border-radius:10px;overflow:hidden;margin:0 auto;">
    <tr>
      <td style="background:#1a1a2e;padding:24px 32px;">
        <h1 style="color:#fff;margin:0;font-size:22px;">{emoji} D to R — Highlight Clips Ready</h1>
      </td>
    </tr>
    <tr>
      <td style="padding:28px 32px;">
        {owner_note}
        <p style="font-size:15px;color:#333;margin-top:16px;">
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
          Delivered automatically by the D to R pipeline.
        </p>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def send_summary_email(
    recipients: list[str],
    clips_links: list[str],
    sport_type: str,
    video_name: str,
) -> None:
    """
    Send an HTML summary email to all recipients.

    The first recipient in the list is treated as the owner (gets an extra operator note).
    Subsequent recipients are the filmed clients (receive only their clips).

    Args:
        recipients:  List of email addresses. recipients[0] = OWNER_EMAIL.
        clips_links: List of Google Drive shareable links.
        sport_type:  "surfing", "football", "mixed", or "other".
        video_name:  Original video filename shown in the subject line.
    """
    if not recipients:
        logger.warning("⚠️ send_summary_email called with empty recipients list")
        return

    emoji   = _SPORT_EMOJI.get(sport_type, "🎬")
    subject = f"{emoji} Your {sport_type.capitalize()} Highlights Are Ready — {video_name}"
    sender  = config.OWNER_EMAIL

    print(f"📧 Sending email to {len(recipients)} recipient(s): {', '.join(recipients)}")

    try:
        service = _get_gmail_service(sender)
    except Exception as e:
        logger.error("❌ Failed to build Gmail service: %s", e)
        print(f"❌ Gmail service setup failed: {e}")
        return

    for i, recipient in enumerate(recipients):
        is_owner = (i == 0)
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = sender
            msg["To"]      = recipient

            html_body = _build_html(clips_links, sport_type, video_name, is_owner=is_owner)
            msg.attach(MIMEText(html_body, "html"))

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            service.users().messages().send(
                userId="me",
                body={"raw": raw},
            ).execute()

            tag = "owner" if is_owner else "client"
            print(f"✅ Email sent → {recipient} ({tag})")
            logger.info("Email sent to %s (%s) for '%s' (%d clips)", recipient, tag, video_name, len(clips_links))

        except Exception as e:
            logger.error("❌ Failed to send email to %s: %s", recipient, e)
            print(f"❌ Email delivery failed for {recipient}: {e}")
