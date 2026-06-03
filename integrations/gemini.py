"""
integrations/gemini.py — Gemini Files API wrapper.
Configures the genai client once and exposes reusable upload/delete helpers.
Import `genai` from here instead of google.generativeai to avoid scattered configure() calls.
"""

import logging
import time

import google.generativeai as genai

import config

logger = logging.getLogger(__name__)

genai.configure(api_key=config.GEMINI_API_KEY)


def upload_video(video_path: str):
    """Upload a video to Gemini Files API and wait until ACTIVE. Returns the file object."""
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
