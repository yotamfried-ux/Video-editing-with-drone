"""
integrations/notifier.py — Gmail delivery via Google service account.
שולח אימייל HTML לבעל הפייפליין ולמצולם (אם נמצא ב-clients.json).
"""

import base64
import json
import logging
import os
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2 import service_account
from googleapiclient.discovery import build

import config

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

_ACTIVITY_EMOJI = {
    "surfing":       "🏄",
    "football":      "⚽",
    "soccer":        "⚽",
    "basketball":    "🏀",
    "skateboarding": "🛹",
    "skiing":        "⛷️",
    "snowboarding":  "🏂",
    "parkour":       "🏃",
    "cycling":       "🚴",
    "motocross":     "🏍️",
    "mixed":         "🎬",
    "other":         "🎬",
    "unknown":       "🎬",
}

# backward compat alias
_SPORT_EMOJI = _ACTIVITY_EMOJI


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
    emoji = _ACTIVITY_EMOJI.get(sport_type, "🎬")
    clip_rows = ""
    for i, link in enumerate(clips_links, start=1):
        label = "▶ Watch / Download Reel" if len(clips_links) == 1 else f"▶ Reel {i}"
        clip_rows += f"""
        <tr>
          <td style="padding:8px 0;">
            <a href="{link}" style="
              display:inline-block;
              padding:12px 28px;
              background:#1a1a2e;
              color:#e0e0ff;
              text-decoration:none;
              border-radius:6px;
              font-weight:600;
              font-size:15px;
            ">{label}</a>
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
          Your highlight reel is ready!<br>
          Extracted from <em>{video_name}</em> — sport detected:
          <strong>{sport_type.capitalize()}</strong>.
        </p>
        <p style="font-size:13px;color:#555;margin-bottom:6px;">
          👇 Click to download your reel, then add music &amp; post directly to Instagram / TikTok.
        </p>
        <p style="font-size:12px;color:#888;margin-bottom:20px;">
          Format: 9:16 vertical · H.264 · ready to upload
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


def _send_via_sportreel_api(
    recipients: list[str],
    clips_links: list[str],
    sport_type: str,
    video_name: str,
) -> str | None:
    """Send through the production SportReel web API, which owns Resend credentials.

    Returns None only when the proxy is not configured. If it is configured,
    delivery errors are raised so qualification cannot silently fall back to a
    broken Gmail service-account impersonation path.
    """
    endpoint = os.getenv("SPORTREEL_NOTIFICATION_API", "").strip()
    operator_secret = os.getenv("OPERATOR_SECRET", "").strip()
    if not endpoint and not operator_secret:
        return None
    if not endpoint or not operator_secret:
        raise RuntimeError(
            "SPORTREEL_NOTIFICATION_API and OPERATOR_SECRET must be configured together"
        )

    payload = json.dumps({
        "recipients": recipients,
        "clips_links": clips_links,
        "sport_type": sport_type,
        "video_name": video_name,
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-operator-secret": operator_secret,
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        if not 200 <= int(response.status) < 300:
            raise RuntimeError(f"SportReel notification API returned HTTP {response.status}")
        raw = response.read()
    try:
        result = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("SportReel notification API returned invalid JSON") from exc
    message_id = result.get("message_id")
    if result.get("ok") is not True or not isinstance(message_id, str) or not message_id.strip():
        raise RuntimeError("SportReel notification API returned no provider message id")
    return message_id.strip()


def send_summary_email(
    recipients: list[str],
    clips_links: list[str],
    sport_type: str,
    video_name: str,
) -> str | None:
    """
    Send an HTML summary email to all recipients.

    Returns the provider message ID when the SportReel / Resend proxy is used.

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

    print(f"📧 Sending email to {len(recipients)} recipient(s): {', '.join(recipients)}")

    provider_message_id = _send_via_sportreel_api(recipients, clips_links, sport_type, video_name)
    if provider_message_id:
        print(f"✅ Delivery notification accepted by SportReel / Resend (message_id={provider_message_id})")
        return provider_message_id

    emoji   = _SPORT_EMOJI.get(sport_type, "🎬")
    subject = f"{emoji} Your {sport_type.capitalize()} Highlights Are Ready — {video_name}"
    sender  = config.OWNER_EMAIL

    try:
        service = _get_gmail_service(sender)
    except Exception as e:
        logger.error("❌ Failed to build Gmail service: %s", e)
        print(f"❌ Gmail service setup failed: {e}")
        return

    for i, recipient in enumerate(recipients):
        is_owner = (recipient == config.OWNER_EMAIL)
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
