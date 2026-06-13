"""Shared pytest fixtures — stub the env vars config.settings requires at import."""

import os

os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
os.environ.setdefault("RAW_FOLDER_ID", "raw")
os.environ.setdefault("PROCESSED_FOLDER_ID", "processed")
os.environ.setdefault("REVIEW_FOLDER_ID", "review")
os.environ.setdefault("APPROVED_FOLDER_ID", "approved")
os.environ.setdefault("OWNER_EMAIL", "owner@example.com")
