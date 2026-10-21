"""Content-addressed cache for expensive LLM analysis responses.

A key combines the SHA-256 of the analysed media, a hash of the exact prompt, the model and a
caller-supplied version tag, so editing the prompt, switching model or changing the footage
always misses. Values are the raw response text, which callers re-parse with the *current*
validators, so a cache hit never bypasses a newer business rule.

The directory ($LLM_CACHE_DIR, default /tmp/llm-cache) is persisted between GitHub runs with
actions/cache. Disable with LLM_CACHE=0. Every function is fail-open: a cache problem
must never break the pipeline.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
from typing import Any

logger = logging.getLogger(__name__)

_hash_lock = threading.Lock()
_file_hash_memo: dict[tuple[str, int, int], str] = {}


def enabled() -> bool:
    return os.getenv("LLM_CACHE", "1").strip().lower() not in {"0", "false", "no", "off"}


def cache_dir() -> str:
    return os.getenv("LLM_CACHE_DIR", "/tmp/llm-cache")


def file_sha256(path: str) -> str:
    stat = os.stat(path)
    memo_key = (os.path.abspath(path), stat.st_size, int(stat.st_mtime))
    with _hash_lock:
        known = _file_hash_memo.get(memo_key)
    if known:
        return known
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    value = digest.hexdigest()
    with _hash_lock:
        _file_hash_memo[memo_key] = value
    return value


def make_key(kind: str, *, media_sha256: str, prompt: str, model: str, version: str = "1", extra: str = "") -> str:
    parts = [kind, version, model, media_sha256, hashlib.sha256(prompt.encode("utf-8")).hexdigest(), extra]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _path(key: str) -> str:
    return os.path.join(cache_dir(), key[:2], f"{key}.json")


def get(key: str) -> str | None:
    if not enabled():
        return None
    try:
        with open(_path(key), encoding="utf-8") as handle:
            payload: dict[str, Any] = json.load(handle)
        text = payload.get("text")
        return text if isinstance(text, str) and text else None
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.debug("LLM cache read failed: %s", exc)
        return None


def put(key: str, text: str, **meta: Any) -> None:
    if not enabled() or not isinstance(text, str) or not text:
        return
    try:
        path = _path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"text": text, **meta}, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:
        logger.debug("LLM cache write failed: %s", exc)
