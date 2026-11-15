"""Tell followers of an athlete that a new reel of that athlete is on Discover.

A customer who bought a reel can ask to be told about more reels of the same athlete (`athlete_follows`).
`athlete_follow_notifications` makes each (follower, reel) pair a one-time event, so a re-run of delivery or an
operator merge never notifies twice. Sending is best effort: a push failure never fails a delivery.
"""
from __future__ import annotations

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def _send_push(messages: list[dict]) -> None:
    request = urllib.request.Request(
        EXPO_PUSH_URL, data=json.dumps(messages).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https URL
        response.read()


def notify_athlete_followers(client, reel_id: str, athlete_id: str | None, send=_send_push) -> int:
    """Notify every follower of `athlete_id` about `reel_id` once. Returns how many followers were notified."""
    if not athlete_id:
        return 0
    try:
        follows = (client.table("athlete_follows").select("id,user_id").eq("athlete_id", athlete_id).execute().data) or []
        if not follows:
            return 0
        reel = (client.table("reels").select("token").eq("id", reel_id).limit(1).execute().data) or []
        token = reel[0].get("token") if reel else None
        notified = 0
        for follow in follows:
            # The insert is the claim: a second attempt for the same pair conflicts and is skipped.
            try:
                client.table("athlete_follow_notifications").insert(
                    {"follow_id": follow["id"], "reel_id": reel_id}).execute()
            except Exception:
                continue
            tokens = (client.table("push_tokens").select("token").eq("user_id", follow["user_id"]).execute().data) or []
            messages = [{
                "to": row["token"],
                "title": "New clip of an athlete you follow",
                "body": "A new SportReel clip is ready to preview.",
                "data": {"screen": "reel", "token": token},
            } for row in tokens if row.get("token")]
            if messages:
                try:
                    send(messages)
                except Exception as exc:
                    logger.warning("Follow push failed for follow %s: %s", follow["id"], exc)
            notified += 1
        return notified
    except Exception as exc:
        logger.warning("Follower notification skipped for reel %s: %s", reel_id, exc)
        return 0
