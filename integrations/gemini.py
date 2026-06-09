"""
integrations/gemini.py — Gemini Files API wrapper (google-genai SDK v2).
Provides a thin compatibility shim so the rest of the codebase continues
to use the old google.generativeai call style unchanged.
"""

import logging
import time

from google import genai as _genai_lib
from google.genai import types as _types

import config

logger = logging.getLogger(__name__)

# ── Single shared client ───────────────────────────────────────────────────

_client: _genai_lib.Client | None = None


def _get_client() -> _genai_lib.Client:
    global _client
    if _client is None:
        _client = _genai_lib.Client(api_key=config.GEMINI_API_KEY)
    return _client


# ── Compatibility wrappers ─────────────────────────────────────────────────

class _Model:
    """Wraps client.models.generate_content to look like GenerativeModel."""

    def __init__(self, model_name: str):
        self._model = model_name

    def generate_content(self, contents, request_options=None):
        client = _get_client()
        # Convert any _CompatFile wrappers back to real SDK File objects
        converted = []
        for item in (contents if isinstance(contents, list) else [contents]):
            converted.append(item._file if isinstance(item, _CompatFile) else item)
        return client.models.generate_content(model=self._model, contents=converted)


class _CompatFile:
    """Wraps google.genai File to expose the same attributes as the old SDK."""

    def __init__(self, file):
        self._file = file

    @property
    def name(self):
        return self._file.name

    @property
    def state(self):
        return self._file.state

    def __getattr__(self, attr):
        return getattr(self._file, attr)


class _GenaiCompat:
    """Module-level shim: exposes the google.generativeai interface via google.genai."""

    def configure(self, api_key=None):
        pass  # client is initialised lazily from config

    def upload_file(self, path: str = None, mime_type: str = None) -> _CompatFile:
        client = _get_client()
        cfg = _types.UploadFileConfig(mime_type=mime_type) if mime_type else None
        kwargs: dict = {"file": path}
        if cfg:
            kwargs["config"] = cfg
        return _CompatFile(client.files.upload(**kwargs))

    def get_file(self, name: str) -> _CompatFile:
        return _CompatFile(_get_client().files.get(name=name))

    def delete_file(self, name: str) -> None:
        try:
            _get_client().files.delete(name=name)
        except Exception as exc:
            logger.debug("delete_file(%s) failed: %s", name, exc)

    def GenerativeModel(self, model_name: str = None, **_kwargs) -> _Model:  # noqa: N802
        return _Model(model_name)


# Public export — import `genai` from here instead of google.generativeai
genai = _GenaiCompat()


# ── Helpers used directly by the pipeline ─────────────────────────────────

def upload_video(video_path: str) -> _CompatFile:
    """Upload a video to Gemini Files API and wait until ACTIVE."""
    from pathlib import Path
    print(f"📤 Uploading '{Path(video_path).name}' to Gemini Files API...")
    try:
        video_file = genai.upload_file(path=video_path)
        _MAX_WAIT = 200
        for _attempt in range(_MAX_WAIT):
            if video_file.state.name != "PROCESSING":
                break
            print(f"  ⏳ Gemini processing video... ({_attempt * 4}s)", end="\r")
            time.sleep(4)
            video_file = genai.get_file(video_file.name)
        else:
            raise RuntimeError(f"Gemini video processing timed out after {_MAX_WAIT * 4}s")
        if video_file.state.name != "ACTIVE":
            raise RuntimeError(f"Gemini file ended in unexpected state: {video_file.state.name}")
        print(f"\n✅ Video ready in Gemini: {video_file.name}")
        return video_file
    except Exception as e:
        logger.error("Gemini upload failed: %s", e)
        raise


def delete_video(video_file) -> None:
    """Delete a Gemini Files API file after use to free storage."""
    try:
        genai.delete_file(video_file.name)
        logger.debug("Deleted Gemini file: %s", video_file.name)
    except Exception as e:
        logger.warning("Could not delete Gemini file %s: %s", video_file.name, e)
