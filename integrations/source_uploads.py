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
    from integrations import qualification
    return qualification.guard_supabase(_client)   # qualification runs: reads only, writes go to the ledger


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


def rekey_source_upload(old_key: str, new_key: str, *, client: Client | None = None) -> bool:
    """Point a source's provenance row at the key it now lives under (flat stage-folder layout).

    Returns True when a row was updated. A row already at ``new_key`` or a source without a row
    is a no-op; a conflicting row at ``new_key`` raises (unique storage_key) so callers fail closed.
    """
    if old_key == new_key:
        return False
    db = client or _supabase()
    now = datetime.now(timezone.utc).isoformat()
    response = (
        db.table("source_uploads")
        .update({"storage_key": new_key, "updated_at": now})
        .eq("storage_key", old_key)
        .execute()
    )
    return bool(response.data)


def resolve_exact_source_duplicate(
    upload_id: str,
    content_sha256: str,
    *,
    client: Client | None = None,
) -> dict[str, Any]:
    db = client or _supabase()
    from integrations import qualification
    if qualification.active():
        return _resolve_recorded_duplicate(db, upload_id, content_sha256)
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


def _resolve_recorded_duplicate(db: Any, upload_id: str, content_sha256: str) -> dict[str, Any]:
    """Qualification runs: the SAME dedup decision, read-only. The production RPC atomically re-decides and may mark
    rows superseded; here the decision production already recorded is reused (row canonical_upload_id) and the bytes
    must still match the recorded content_sha256. Nothing is written."""
    from integrations import qualification

    row = (db.table("source_uploads").select("id,storage_key,status,content_sha256,canonical_upload_id")
           .eq("id", upload_id).limit(1).execute()).data
    if not row:
        raise RuntimeError(f"qualification dedup: no source_uploads row {upload_id}")
    row = row[0]
    recorded = str(row.get("content_sha256") or "")
    if recorded and recorded != content_sha256:
        raise RuntimeError(f"qualification dedup: bytes of {row.get('storage_key')} differ from the recorded SHA-256")
    canonical_id = str(row.get("canonical_upload_id") or row["id"])
    canonical = row
    if canonical_id != str(row["id"]):
        found = (db.table("source_uploads").select("id,storage_key").eq("id", canonical_id).limit(1).execute()).data
        if not found:
            raise RuntimeError(f"qualification dedup: canonical upload {canonical_id} not found")
        canonical = found[0]
    qualification.record("dedup_read_only", upload_id=upload_id, canonical_upload_id=canonical_id,
                         content_sha256=content_sha256, sha_matches_record=bool(recorded))
    return {"canonical": {"upload_id": str(canonical["id"]), "storage_key": canonical["storage_key"]}, "superseded": []}
