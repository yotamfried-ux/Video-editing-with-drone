"""Durable source-upload manifest access for exact-content duplicate control."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

import config

_client: Client | None = None


def _supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
    return _client


def get_source_upload(storage_key: str, *, client: Client | None = None) -> dict[str, Any] | None:
    db = client or _supabase()
    response = (
        db.table("source_uploads")
        .select(
            "id,batch_id,storage_key,status,source_size_bytes,verified_size_bytes,"
            "verified_at,content_sha256,canonical_upload_id,removed_at"
        )
        .eq("storage_key", storage_key)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def resolve_exact_source_duplicate(
    upload_id: str,
    content_sha256: str,
    *,
    client: Client | None = None,
) -> dict[str, Any]:
    db = client or _supabase()
    response = db.rpc(
        "resolve_exact_source_duplicate",
        {"p_upload_id": upload_id, "p_content_sha256": content_sha256},
    ).execute()
    payload: Any = response.data
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        payload = payload[0]
    if not isinstance(payload, dict) or not isinstance(payload.get("canonical"), dict):
        raise RuntimeError("Exact-source dedup RPC returned an invalid payload")
    if not isinstance(payload.get("superseded"), list):
        payload["superseded"] = []
    return payload


def mark_source_removed(
    upload_id: str,
    canonical_upload_id: str,
    *,
    client: Client | None = None,
) -> None:
    db = client or _supabase()
    removed_at = datetime.now(timezone.utc).isoformat()
    db.table("source_uploads").update(
        {"removed_at": removed_at, "removal_error": None, "updated_at": removed_at}
    ).eq("id", upload_id).eq("status", "superseded").execute()
    db.table("source_upload_dedup_audit").update(
        {"removed_at": removed_at, "removal_error": None}
    ).eq("superseded_upload_id", upload_id).eq(
        "canonical_upload_id", canonical_upload_id
    ).eq("reason", "exact_content_duplicate").execute()


def mark_source_removal_error(
    upload_id: str,
    canonical_upload_id: str,
    error: str,
    *,
    client: Client | None = None,
) -> None:
    db = client or _supabase()
    now = datetime.now(timezone.utc).isoformat()
    message = error[:1000]
    db.table("source_uploads").update(
        {"removal_error": message, "updated_at": now}
    ).eq("id", upload_id).eq("status", "superseded").execute()
    db.table("source_upload_dedup_audit").update(
        {"removal_error": message}
    ).eq("superseded_upload_id", upload_id).eq(
        "canonical_upload_id", canonical_upload_id
    ).eq("reason", "exact_content_duplicate").execute()
