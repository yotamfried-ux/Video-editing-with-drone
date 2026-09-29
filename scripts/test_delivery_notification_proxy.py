#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("OWNER_EMAIL", "owner@example.com")

from integrations import notifier


class _Response:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return b'{"ok":true}'


class DeliveryNotificationProxyTest(unittest.TestCase):
    def test_summary_email_uses_authenticated_sportreel_notification_api(self):
        os.environ["SPORTREEL_NOTIFICATION_API"] = "https://example.test/api/operator/delivery-notify"
        os.environ["OPERATOR_SECRET"] = "test-secret"

        captured = {}
        def fake_urlopen(req, timeout=0):
            captured["url"] = req.full_url
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            captured["body"] = json.loads(req.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response()

        with patch("urllib.request.urlopen", fake_urlopen):
            notifier.send_summary_email(
                ["owner@example.com"],
                ["https://example.test/reel/abc"],
                "surfing",
                "fixture.mp4",
            )

        self.assertEqual(captured["url"], os.environ["SPORTREEL_NOTIFICATION_API"])
        self.assertEqual(captured["headers"]["x-operator-secret"], "test-secret")
        self.assertEqual(captured["body"]["recipients"], ["owner@example.com"])
        self.assertEqual(captured["body"]["clips_links"], ["https://example.test/reel/abc"])
        self.assertEqual(captured["body"]["sport_type"], "surfing")
        self.assertEqual(captured["body"]["video_name"], "fixture.mp4")
        self.assertGreater(captured["timeout"], 0)


if __name__ == "__main__":
    unittest.main()
