"""
config.py — Load all pipeline configuration from environment variables.
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
