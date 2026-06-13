"""
config/settings.py — Load all pipeline configuration from environment variables.
All secrets must be set in .env (copy from .env.example).
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Gemini AI (Google) ────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL: str   = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

# ── Google Service Account ─────────────────────────────────────────────────
GOOGLE_SERVICE_ACCOUNT_JSON: str = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

# ── Google Drive folder IDs ────────────────────────────────────────────────
RAW_FOLDER_ID: str       = os.environ["RAW_FOLDER_ID"]           # incoming raw footage
PROCESSED_FOLDER_ID: str = os.environ["PROCESSED_FOLDER_ID"]     # archived originals
REVIEW_FOLDER_ID: str    = os.environ["REVIEW_FOLDER_ID"]        # draft reels awaiting approval
APPROVED_FOLDER_ID: str        = os.environ["APPROVED_FOLDER_ID"]        # approved → ready to deliver
PREVIEW_FOLDER_ID: str         = os.getenv("PREVIEW_FOLDER_ID", "")         # 480p watermarked previews sent to athletes
PENDING_PAYMENT_FOLDER_ID: str = os.getenv("PENDING_PAYMENT_FOLDER_ID", "") # full reels awaiting payment
CLIPS_FOLDER_ID: str           = os.getenv("CLIPS_FOLDER_ID", "")           # unused by current pipeline (reserved)

# ── Delivery ───────────────────────────────────────────────────────────────
OWNER_EMAIL: str = os.environ["OWNER_EMAIL"]               # pipeline operator — always receives summary
NOTIFY_EMAIL: str = os.getenv("NOTIFY_EMAIL", "")          # fallback client email (used if clients.json has no match)

# ── Local paths ────────────────────────────────────────────────────────────
LOGO_PATH: str = os.getenv("LOGO_PATH", "assets/logo.png")
MUSIC_DIR: str = os.getenv("MUSIC_DIR", "music")
TMP_DIR: str = os.getenv("TMP_DIR", "/tmp/dtor")
PROCESSED_IDS_FILE: str = "processed.json"                 # local state file
LOG_FILE: str = "logs/pipeline.log"
CLIENTS_FILE: str = "clients.json"                         # maps video patterns → client emails
MAX_CUT_WORKERS: int = int(os.getenv("MAX_CUT_WORKERS", str(min(4, os.cpu_count() or 1))))
CLIPS_CACHE_DIR: str    = os.getenv("CLIPS_CACHE_DIR", "/tmp/dtor_clips")
FEEDBACK_FILE: str          = os.getenv("FEEDBACK_FILE", "labels_feedback.json")
OPERATOR_NOTES_FILE: str    = os.getenv("OPERATOR_NOTES_FILE", "operator_notes.json")
REEL_METADATA_FILE: str = os.getenv("REEL_METADATA_FILE", "reels_metadata.json")
QA_CROP_CHECK: bool      = os.getenv("QA_CROP_CHECK", "false").lower() == "true"
QA_REEL_CHECK: bool      = os.getenv("QA_REEL_CHECK", "true").lower() == "true"
# Reel-level social-media QA thresholds (TikTok + Instagram; advisory, calibratable)
QA_ENGAGEMENT_THRESHOLD: int = int(os.getenv("QA_ENGAGEMENT_THRESHOLD", "60"))
QA_DUR_OK_MIN: float         = float(os.getenv("QA_DUR_OK_MIN", "7"))
# Aligned with the editor's TARGET_REEL_MAX (85s) — flag only true outliers.
QA_DUR_OK_MAX: float         = float(os.getenv("QA_DUR_OK_MAX", "90"))
QA_RESULTS_FILE: str         = os.getenv("QA_RESULTS_FILE", "qa_results.jsonl")
# QA gate: when a reel FAILs with critical defects, automatically re-edit
# (drop/fix the offending clips) and re-check, up to QA_MAX_RETRIES times.
# Reels still failing after retries are uploaded with a QA-FLAGGED name.
QA_GATE: bool       = os.getenv("QA_GATE", "true").lower() == "true"
QA_MAX_RETRIES: int = int(os.getenv("QA_MAX_RETRIES", "2"))
PENDING_UPLOADS_DIR: str = os.getenv("PENDING_UPLOADS_DIR", "pending_uploads")
QUALITY_LOG_FILE: str    = os.getenv("QUALITY_LOG_FILE", "quality_issues.jsonl")

# ── Editorial quality gates ───────────────────────────────────────────────────
# Events shorter than this (real content, before any padding) are dropped —
# a 2s fragment has no visible performance and ruins the hook.
MIN_EVENT_SEC: float = float(os.getenv("MIN_EVENT_SEC", "5"))
# Sources below this height get a quality warning + forced basic mode (no zoom).
MIN_SOURCE_HEIGHT: int = int(os.getenv("MIN_SOURCE_HEIGHT", "720"))
# Motion-interpolated slow-mo for sources below 50fps (optical flow, slower encode).
SLOWMO_INTERPOLATE: bool = os.getenv("SLOWMO_INTERPOLATE", "true").lower() == "true"
# Burn athlete identity description as lower-third text. Off — the identity
# string ("red shirt #7") is an internal matching label, not viewer content.
ATHLETE_TEXT_OVERLAY: bool = os.getenv("ATHLETE_TEXT_OVERLAY", "false").lower() == "true"

# ── SportReel platform (Supabase + Cloudflare Stream) ────────────────────────
SUPABASE_URL: str              = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str      = os.getenv("SUPABASE_SERVICE_KEY", "")
CLOUDFLARE_ACCOUNT_ID: str     = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_STREAM_API_TOKEN: str = os.getenv("CLOUDFLARE_STREAM_API_TOKEN", "")
CLOUDFLARE_CUSTOMER_CODE: str  = os.getenv("CLOUDFLARE_CUSTOMER_CODE", "")
APP_DOMAIN: str                = os.getenv("APP_DOMAIN", "sportreel.app")

# ── Subprocess / API timeouts (seconds) ──────────────────────────────────────
# Previously hardcoded across analyzer.py / editor.py / integrations. Centralized
# so slow CI runners or long 4K sources can be tuned without code changes.
FFPROBE_TIMEOUT: int            = int(os.getenv("FFPROBE_TIMEOUT", "30"))
FFMPEG_CHUNK_TIMEOUT: int       = int(os.getenv("FFMPEG_CHUNK_TIMEOUT", "120"))
FFMPEG_PROXY_TIMEOUT: int       = int(os.getenv("FFMPEG_PROXY_TIMEOUT", "300"))
FFMPEG_CLIP_TIMEOUT: int        = int(os.getenv("FFMPEG_CLIP_TIMEOUT", "300"))
FFMPEG_CLIP_INTERP_TIMEOUT: int = int(os.getenv("FFMPEG_CLIP_INTERP_TIMEOUT", "900"))
FFMPEG_REEL_TIMEOUT: int        = int(os.getenv("FFMPEG_REEL_TIMEOUT", "600"))
FFMPEG_FRAME_TIMEOUT: int       = int(os.getenv("FFMPEG_FRAME_TIMEOUT", "30"))
FFMPEG_LOOP_TIMEOUT: int        = int(os.getenv("FFMPEG_LOOP_TIMEOUT", "60"))
GEMINI_CLIP_QA_TIMEOUT: int     = int(os.getenv("GEMINI_CLIP_QA_TIMEOUT", "30"))
GEMINI_REEL_QA_TIMEOUT: int     = int(os.getenv("GEMINI_REEL_QA_TIMEOUT", "120"))
GEMINI_SESSION_TIMEOUT: int     = int(os.getenv("GEMINI_SESSION_TIMEOUT", "300"))
STREAM_UPLOAD_TIMEOUT: int      = int(os.getenv("STREAM_UPLOAD_TIMEOUT", "300"))

# ── Concurrency / file thresholds ─────────────────────────────────────────────
LARGE_FILE_BYTES: int      = int(os.getenv("LARGE_FILE_BYTES", str(100_000_000)))
MAX_UL_WORKERS: int        = int(os.getenv("MAX_UL_WORKERS", "3"))
MIN_FREE_GB: float         = float(os.getenv("MIN_FREE_GB", "5.0"))
UPLOAD_RETRY_ATTEMPTS: int = int(os.getenv("UPLOAD_RETRY_ATTEMPTS", "4"))

# ── Analysis proxy (pre-Gemini downscale) ─────────────────────────────────────
# Drone footage has small, detail-critical subjects; crf 28/veryfast/1280 lost
# board colors and far surfers, hurting identity + scoring accuracy.
PROXY_MAX_WIDTH: int = int(os.getenv("PROXY_MAX_WIDTH", "1600"))
PROXY_CRF: int       = int(os.getenv("PROXY_CRF", "23"))
PROXY_PRESET: str    = os.getenv("PROXY_PRESET", "faster")

# ── Identity clustering (CLIP re-ID) ──────────────────────────────────────────
# CLIP cosine similarity bands. Pairs in [CLIP_MERGE_THRESHOLD, CLIP_HIGH_CONF)
# require a second signal (Gemini visual "same person?") before merging; pairs
# >= CLIP_HIGH_CONF merge directly; below the threshold never merge.
CLIP_MERGE_THRESHOLD: float = float(os.getenv("CLIP_MERGE_THRESHOLD", "0.78"))
CLIP_HIGH_CONF: float       = float(os.getenv("CLIP_HIGH_CONF", "0.88"))
# Frames sampled per person for identity evidence (multi-frame > single thumb).
IDENTITY_FRAMES: int        = int(os.getenv("IDENTITY_FRAMES", "5"))
# Optional mild duration weighting of moment scores (auditable, off by default).
SCORE_DURATION_WEIGHT: bool = os.getenv("SCORE_DURATION_WEIGHT", "false").lower() == "true"

# ── LangSmith observability (optional) ────────────────────────────────────────
# Set LANGSMITH_API_KEY + LANGSMITH_TRACING=true to enable tracing.
# Without these vars @traceable decorators are no-ops — no crash in production.
LANGSMITH_TRACING: bool = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_PROJECT: str  = os.getenv("LANGSMITH_PROJECT", "drone-video-pipeline")

# ── Sentry error monitoring (optional) ────────────────────────────────────────
# Set SENTRY_DSN to enable. Empty DSN → init_sentry() is a no-op (no crash).
SENTRY_DSN: str                  = os.getenv("SENTRY_DSN", "")
SENTRY_ENVIRONMENT: str          = os.getenv("SENTRY_ENVIRONMENT", "production")
SENTRY_TRACES_SAMPLE_RATE: float = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0"))
