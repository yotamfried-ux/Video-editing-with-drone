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
FEEDBACK_FILE: str      = os.getenv("FEEDBACK_FILE", "labels_feedback.json")
REEL_METADATA_FILE: str = os.getenv("REEL_METADATA_FILE", "reels_metadata.json")
QA_CROP_CHECK: bool      = os.getenv("QA_CROP_CHECK", "false").lower() == "true"
QA_REEL_CHECK: bool      = os.getenv("QA_REEL_CHECK", "true").lower() == "true"
# Reel-level social-media QA thresholds (TikTok + Instagram; advisory, calibratable)
QA_ENGAGEMENT_THRESHOLD: int = int(os.getenv("QA_ENGAGEMENT_THRESHOLD", "60"))
QA_DUR_OK_MIN: float         = float(os.getenv("QA_DUR_OK_MIN", "7"))
QA_DUR_OK_MAX: float         = float(os.getenv("QA_DUR_OK_MAX", "60"))
QA_RESULTS_FILE: str         = os.getenv("QA_RESULTS_FILE", "qa_results.jsonl")
PENDING_UPLOADS_DIR: str = os.getenv("PENDING_UPLOADS_DIR", "pending_uploads")
QUALITY_LOG_FILE: str    = os.getenv("QUALITY_LOG_FILE", "quality_issues.jsonl")

# ── SportReel platform (Supabase + Cloudflare Stream) ────────────────────────
SUPABASE_URL: str              = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str      = os.getenv("SUPABASE_SERVICE_KEY", "")
CLOUDFLARE_ACCOUNT_ID: str     = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_STREAM_API_TOKEN: str = os.getenv("CLOUDFLARE_STREAM_API_TOKEN", "")
CLOUDFLARE_CUSTOMER_CODE: str  = os.getenv("CLOUDFLARE_CUSTOMER_CODE", "")
APP_DOMAIN: str                = os.getenv("APP_DOMAIN", "sportreel.app")

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
