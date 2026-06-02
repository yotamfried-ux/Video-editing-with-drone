"""
pipeline/clients.py — Client lookup from clients.json.
Matches a person description or draft filename against registered client patterns.
"""

import json
import logging

import config

logger = logging.getLogger(__name__)


def find_client(description: str) -> dict | None:
    """
    Match a person description or draft filename against clients.json patterns.

    clients.json format:
      [{"name": "Yoni S.", "email": "yoni@example.com", "video_pattern": "yoni"}]

    Matching is case-insensitive substring search on `video_pattern` inside `description`.
    Returns the first matching client dict, or None if no match / file missing.
    """
    try:
        with open(config.CLIENTS_FILE) as f:
            clients: list[dict] = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not read %s: %s", config.CLIENTS_FILE, e)
        return None

    lower = description.lower()
    for client in clients:
        jersey = str(client.get("jersey_number", "")).strip()
        if jersey and (
            f"#{jersey}" in lower
            or f"number {jersey}" in lower
            or f"no. {jersey}" in lower
            or f" {jersey} " in lower
            or lower.endswith(f" {jersey}")
        ):
            return client
        pattern = client.get("video_pattern", "").lower()
        if pattern and pattern in lower:
            return client

    return None
