"""Manifest-driven RAW/PROCESSED reconciliation for one durable upload batch.

A pipeline attempt moves each admitted source ``raw/<batch>/<name>`` to
``processed/<batch>/<name>`` (``mark_as_processed``).  A retry of the same
verified batch therefore starts with its frozen inputs under ``processed/``.
This module is the single authority that puts exactly those objects back:

* the frozen ``input_manifest`` is the only source of truth for what to touch;
* every object is checked (existence + verified size, optionally SHA-256)
  *before* anything is copied, and nothing is changed unless the whole manifest
  is recoverable;
* a copy is verified before the processed original is deleted;
* the operation is idempotent and never overwrites a RAW object;
* it never lists or touches anything outside ``raw/<batch>/`` and
  ``processed/<batch>/``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

logger = logging.getLogger(__name__)

RAW_PREFIX = "raw/"
PROCESSED_PREFIX = "processed/"
_MAX_COPY_OBJECT_BYTES = 5 * 1024**3
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mts", ".mxf"}


class FrozenInputError(RuntimeError):
    """The frozen batch inputs cannot be proven present and correct."""


class Store(Protocol):
    def head(self, key: str) -> dict[str, Any] | None: ...
    def list(self, prefix: str) -> list[dict[str, Any]]: ...
    def copy(self, source_key: str, dest_key: str) -> None: ...
    def delete(self, key: str) -> None: ...
    def sha256(self, key: str) -> str: ...


@dataclass(frozen=True)
class ManifestEntry:
    key: str
    filename: str
    size: int
    sha256: str | None = None
    upload_id: str | None = None

    @property
    def processed_key(self) -> str:
        return processed_key_for(self.key)

    @property
    def legacy_flat_keys(self) -> list[str]:
        """Un-namespaced layouts produced by the old global restore (``raw/<name>``)."""
        name = self.key.rsplit("/", 1)[-1]
        return [f"{RAW_PREFIX}{name}", f"{PROCESSED_PREFIX}{name}"]


@dataclass
class EntryReport:
    key: str
    filename: str
    expected_size: int
    state: str  # raw_ok | restorable | restored | missing | size_mismatch | conflict
    raw_size: int | None = None
    processed_size: int | None = None
    detail: str = ""
    source_key: str | None = None  # where a restorable/restored object comes from
    legacy: bool = False


@dataclass
class Report:
    batch_id: str
    expected: int
    entries: list[EntryReport] = field(default_factory=list)
    unexpected_raw: list[str] = field(default_factory=list)
    processed_not_in_manifest: int = 0
    restored: int = 0
    verified: int = 0

    def count(self, state: str) -> int:
        return sum(1 for entry in self.entries if entry.state == state)

    def failures(self) -> list[EntryReport]:
        return [e for e in self.entries if e.state in {"missing", "size_mismatch", "conflict"}]

    def summary(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "expected": self.expected,
            "in_raw": self.count("raw_ok"),
            "restorable_from_processed": self.count("restorable"),
            "restored": self.restored,
            "missing": self.count("missing"),
            "size_mismatch": self.count("size_mismatch"),
            "conflict": self.count("conflict"),
            "unexpected_raw": len(self.unexpected_raw),
            "processed_not_in_manifest_untouched": self.processed_not_in_manifest,
            "verified": self.verified,
        }


def processed_key_for(raw_key: str) -> str:
    if not raw_key.startswith(RAW_PREFIX):
        raise FrozenInputError(f"manifest key is not under {RAW_PREFIX}: {raw_key!r}")
    return PROCESSED_PREFIX + raw_key[len(RAW_PREFIX):]


def safe_batch_id(value: str | None) -> str:
    raw = (value or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw).strip("_")
    return safe[:80]


def load_manifest_from_env() -> list[dict[str, Any]]:
    raw = (os.getenv("SPORTREEL_INPUT_MANIFEST_JSON") or "").strip()
    encoded = (os.getenv("SPORTREEL_INPUT_MANIFEST_B64") or "").strip()
    if not raw and encoded:
        try:
            raw = base64.b64decode(encoded, validate=True).decode("utf-8")
        except Exception as exc:
            raise FrozenInputError("SPORTREEL_INPUT_MANIFEST_B64 is invalid") from exc
    if not raw:
        raise FrozenInputError("frozen input manifest is absent")
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FrozenInputError("frozen input manifest is not valid JSON") from exc
    if not isinstance(manifest, list):
        raise FrozenInputError("frozen input manifest must be a list")
    return manifest


def parse_manifest(manifest: Iterable[Any], batch_id: str) -> list[ManifestEntry]:
    """Validate the frozen manifest strictly; any ambiguity is fatal."""
    batch = safe_batch_id(batch_id)
    if not batch:
        raise FrozenInputError("explicit batch id is required")
    scope = f"{RAW_PREFIX}{batch}/"
    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(manifest):
        if not isinstance(item, dict):
            raise FrozenInputError(f"manifest entry {index} is not an object")
        key = str(item.get("storage_key") or item.get("key") or "").strip()
        if not key.startswith(scope) or "/" in key[len(scope):] or len(key) == len(scope):
            raise FrozenInputError(
                f"manifest entry {index} is outside the batch scope {scope!r} (multiple batches or bad key)"
            )
        if key in seen:
            raise FrozenInputError(f"manifest lists {key!r} twice")
        seen.add(key)
        try:
            verified = int(item["verified_size_bytes"])
            declared = int(item["source_size_bytes"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FrozenInputError(f"manifest entry {index} lacks verified/declared sizes") from exc
        if verified <= 0 or verified != declared:
            raise FrozenInputError(f"manifest entry {index} has unverified size ({declared} vs {verified})")
        sha = item.get("content_sha256")
        sha = str(sha).strip().lower() if sha else None
        if sha is not None and (len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha)):
            raise FrozenInputError(f"manifest entry {index} has a malformed content_sha256")
        entries.append(
            ManifestEntry(
                key=key,
                filename=str(item.get("source_filename") or key.rsplit("/", 1)[-1]),
                size=verified,
                sha256=sha,
                upload_id=str(item["upload_id"]) if item.get("upload_id") else None,
            )
        )
    if not entries:
        raise FrozenInputError("frozen input manifest is empty")
    return entries


def _size(meta: dict[str, Any] | None) -> int | None:
    if meta is None:
        return None
    return int(meta.get("Size", meta.get("ContentLength", 0)))


def _is_video(key: str) -> bool:
    return os.path.splitext(key)[1].lower() in _VIDEO_EXTS


def reconcile_frozen_inputs(
    store: Store,
    manifest: Iterable[Any],
    batch_id: str,
    *,
    restore: bool = True,
    verify_sha256: bool = False,
    expected_sha256: dict[str, str] | None = None,
    recover_legacy_flat: bool = False,
) -> Report:
    """Reconcile RAW against the frozen manifest, restoring from PROCESSED if allowed.

    Raises :class:`FrozenInputError` (without having changed anything) when any
    manifest entry is unrecoverable, mismatched, or when RAW holds unexpected
    video objects for the batch.  ``restore=False`` is a read-only audit.
    ``expected_sha256`` supplies independent content identities (key -> sha256)
    when the manifest itself does not carry them.  ``recover_legacy_flat``
    additionally searches the un-namespaced ``raw/<name>`` / ``processed/<name>``
    layout left by the old global restore; because a flat key proves nothing
    about batch membership, such a source is accepted only with a matching size
    AND a verified SHA-256 equal to the durable content identity.
    """
    batch = safe_batch_id(batch_id)
    entries = parse_manifest(manifest, batch)
    if expected_sha256:
        entries = [
            ManifestEntry(e.key, e.filename, e.size, e.sha256 or expected_sha256.get(e.key), e.upload_id)
            for e in entries
        ]
    report = Report(batch_id=batch, expected=len(entries))
    expected_raw = {e.key for e in entries}

    raw_listing = {str(o["Key"]): o for o in store.list(f"{RAW_PREFIX}{batch}/")}
    processed_listing = {str(o["Key"]): o for o in store.list(f"{PROCESSED_PREFIX}{batch}/")}
    report.unexpected_raw = sorted(k for k in raw_listing if k not in expected_raw and _is_video(k))
    report.processed_not_in_manifest = len(
        [k for k in processed_listing if k not in {e.processed_key for e in entries}]
    )

    for entry in entries:
        raw_meta = store.head(entry.key)
        proc_meta = store.head(entry.processed_key)
        rs, ps = _size(raw_meta), _size(proc_meta)
        item = EntryReport(entry.key, entry.filename, entry.size, "missing", rs, ps)
        if raw_meta is not None:
            if rs != entry.size:
                item.state, item.detail = "size_mismatch", f"raw size {rs} != verified {entry.size}"
            else:
                item.state = "raw_ok"
        elif proc_meta is not None:
            if ps != entry.size:
                item.state, item.detail = "size_mismatch", f"processed size {ps} != verified {entry.size}"
            elif entry.size > _MAX_COPY_OBJECT_BYTES:
                item.state, item.detail = "conflict", "object exceeds single-copy limit"
            else:
                item.state, item.source_key = "restorable", entry.processed_key
        else:
            item.detail = "absent from raw and processed"
            if recover_legacy_flat:
                for flat_key in entry.legacy_flat_keys:
                    flat_meta = store.head(flat_key)
                    if flat_meta is None or _size(flat_meta) != entry.size:
                        continue
                    if entry.sha256 is None:
                        item.detail = f"legacy flat object {flat_key} has no durable content identity to prove it"
                        break
                    if entry.size > _MAX_COPY_OBJECT_BYTES:
                        break
                    item.state, item.source_key, item.legacy, item.detail = "restorable", flat_key, True, ""
                    break
        report.entries.append(item)

    problems = report.failures()
    if report.unexpected_raw:
        problems_text = f"{len(report.unexpected_raw)} unexpected video object(s) in raw/{batch}/"
    else:
        problems_text = ""
    if problems or problems_text:
        lines = [f"{p.state}: {p.filename} ({p.detail})" for p in problems[:5]]
        if problems_text:
            lines.append(problems_text)
        raise FrozenInputError(
            f"frozen inputs for {batch} are not recoverable: {json.dumps(report.summary())}; " + "; ".join(lines)
        )

    if verify_sha256 or recover_legacy_flat:
        for entry, item in zip(entries, report.entries):
            if not verify_sha256 and not item.legacy:
                continue
            if entry.sha256 is None:
                raise FrozenInputError(f"no content identity available to verify {entry.filename}")
            location = entry.key if item.state == "raw_ok" else str(item.source_key)
            actual = store.sha256(location)
            if actual != entry.sha256:
                item.state, item.detail = "conflict", "sha256 differs from frozen identity"
        if report.failures():
            raise FrozenInputError(
                f"frozen inputs for {batch} failed content verification: {json.dumps(report.summary())}"
            )

    if not restore:
        return report

    for entry, item in zip(entries, report.entries):
        if item.state != "restorable":
            continue
        store.copy(str(item.source_key), entry.key)
        copied = store.head(entry.key)
        if _size(copied) != entry.size:
            store.delete(entry.key)  # remove only the copy this call created
            raise FrozenInputError(f"restore of {entry.filename} produced size {_size(copied)} != {entry.size}")
        if entry.sha256 is not None and (verify_sha256 or item.legacy) and store.sha256(entry.key) != entry.sha256:
            store.delete(entry.key)
            raise FrozenInputError(f"restore of {entry.filename} failed sha256 verification")
        store.delete(str(item.source_key))
        item.state, item.raw_size = "restored", entry.size
        report.restored += 1
        logger.info("restored frozen input %s from processed/", entry.key)

    final_raw = {str(o["Key"]): o for o in store.list(f"{RAW_PREFIX}{batch}/")}
    final_videos = {k for k in final_raw if _is_video(k)}
    if final_videos != expected_raw:
        raise FrozenInputError(
            f"post-restore raw/{batch}/ differs from manifest: "
            f"missing={len(expected_raw - final_videos)} unexpected={len(final_videos - expected_raw)}"
        )
    for entry in entries:
        if _size(store.head(entry.key)) != entry.size:
            raise FrozenInputError(f"post-restore size mismatch for {entry.filename}")
        report.verified += 1
    return report


class R2Store:
    """boto3-backed store using the project's R2 client factory."""

    def __init__(self) -> None:
        from integrations import r2_storage

        self._r2 = r2_storage
        self._client = r2_storage._client()
        self._bucket = r2_storage._bucket()

    def head(self, key: str) -> dict[str, Any] | None:
        from botocore.exceptions import ClientError

        try:
            return self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return None
            raise

    def list(self, prefix: str) -> list[dict[str, Any]]:
        return self._r2.list_objects(prefix)

    def copy(self, source_key: str, dest_key: str) -> None:
        self._client.copy(
            {"Bucket": self._bucket, "Key": source_key}, self._bucket, dest_key,
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def sha256(self, key: str) -> str:
        digest = hashlib.sha256()
        body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
        for chunk in iter(lambda: body.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()
