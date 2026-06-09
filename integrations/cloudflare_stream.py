"""Cloudflare Stream integration — upload videos and generate signed URLs."""

import hashlib
import hmac
import time
import requests
import config


def upload_to_stream(local_path: str) -> str:
    """Upload a local MP4 to Cloudflare Stream, return the stream UID."""
    url = f"https://api.cloudflare.com/client/v4/accounts/{config.CLOUDFLARE_ACCOUNT_ID}/stream"
    headers = {"Authorization": f"Bearer {config.CLOUDFLARE_STREAM_API_TOKEN}"}
    with open(local_path, "rb") as f:
        resp = requests.post(url, headers=headers, files={"file": f}, timeout=300)
    resp.raise_for_status()
    return resp.json()["result"]["uid"]


def get_signed_stream_url(stream_uid: str, ttl_seconds: int = 3600) -> str:
    """Return a signed Cloudflare Stream URL valid for ttl_seconds."""
    exp = int(time.time()) + ttl_seconds
    token_path = f"/sign/{stream_uid}"
    payload = f"{stream_uid}.{exp}"
    sig = hmac.new(
        config.CLOUDFLARE_STREAM_API_TOKEN.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"https://customer-{config.CLOUDFLARE_CUSTOMER_CODE}.cloudflarestream.com/{stream_uid}/manifest/video.m3u8?token={sig}&exp={exp}"
