"""
pipeline/preflight.py — startup health checks.

Run before the pipeline does any real work so a misconfigured environment fails
fast with a clear report instead of mid-run. Required checks raise RuntimeError;
optional ones only warn (Supabase/Sentry are optional features).
"""

import logging
import shutil

import config

logger = logging.getLogger(__name__)


def _check_ffmpeg() -> tuple[str, bool, str]:
    ok = bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe"))
    return ("ffmpeg/ffprobe on PATH", ok,
            "" if ok else "install ffmpeg (sudo apt install ffmpeg)")


def _check_gemini_key() -> tuple[str, bool, str]:
    ok = bool(getattr(config, "GEMINI_API_KEY", ""))
    return ("GEMINI_API_KEY set", ok, "" if ok else "GEMINI_API_KEY is empty")


def _check_drive() -> tuple[str, bool, str]:
    try:
        from integrations.drive import _get_drive_service
        svc = _get_drive_service()
        svc.files().list(pageSize=1, fields="files(id)").execute()
        return ("Google Drive reachable", True, "")
    except Exception as exc:
        return ("Google Drive reachable", False, str(exc)[:160])


def _check_disk() -> tuple[str, bool, str]:
    import os
    try:
        os.makedirs(config.TMP_DIR, exist_ok=True)
        free = shutil.disk_usage(config.TMP_DIR).free / (1024 ** 3)
        ok = free >= config.MIN_FREE_GB
        return (f"disk space ≥{config.MIN_FREE_GB}GB", ok,
                "" if ok else f"only {free:.1f}GB free in {config.TMP_DIR}")
    except Exception as exc:
        return ("disk space", False, str(exc)[:160])


def _check_supabase() -> tuple[str, bool, str]:
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return ("Supabase configured (optional)", True, "not configured — skipped")
    try:
        from integrations.supabase_uploader import _supabase
        _supabase().table("pipeline_status").select("id").limit(1).execute()
        return ("Supabase reachable", True, "")
    except Exception as exc:
        return ("Supabase reachable (optional)", True, f"warn: {str(exc)[:120]}")


def _check_sentry() -> tuple[str, bool, str]:
    ok = bool(config.SENTRY_DSN)
    return ("Sentry DSN (optional)", True, "" if ok else "not configured — errors only logged locally")


# (check_fn, required) — required failures abort the run; optional ones warn.
_REQUIRED = [_check_ffmpeg, _check_gemini_key, _check_drive, _check_disk]
_OPTIONAL = [_check_supabase, _check_sentry]


def run_preflight_checks() -> None:
    """Run all checks, print a report, and raise RuntimeError if any REQUIRED check fails."""
    print("\n🩺 Preflight checks")
    failures: list[str] = []

    for fn in _REQUIRED:
        name, ok, detail = fn()
        print(f"  {'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{name}: {detail}")

    for fn in _OPTIONAL:
        name, ok, detail = fn()
        mark = "✅" if ok and not detail.startswith("warn") else "⚠️"
        print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))

    if failures:
        raise RuntimeError("Preflight failed:\n  - " + "\n  - ".join(failures))
    print("  ✅ all required checks passed\n")
