"""Config capability boundaries: delivery can import without pipeline-only secrets."""
import os, subprocess, sys

def test_delivery_import_does_not_require_gemini():
    env = os.environ.copy()
    for key in ("GEMINI_API_KEY","RAW_FOLDER_ID","PROCESSED_FOLDER_ID","REVIEW_FOLDER_ID"):
        env.pop(key, None)
    env.setdefault("STORAGE_BACKEND","r2")
    result = subprocess.run(
        [sys.executable, "-c", "import services.delivery; print('delivery-import-ok')"],
        env=env, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert "delivery-import-ok" in result.stdout

def test_gemini_key_is_checked_at_use():
    env = os.environ.copy()
    env.pop("GEMINI_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", "from integrations.gemini import _get_client; _get_client()"],
        env=env, text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert "GEMINI_API_KEY is required when Gemini is used" in result.stderr
