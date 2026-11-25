import unittest
from datetime import date

from scripts.check_gemini_model_notice import (
    mail_message,
    needs_notice,
    pipeline_model,
    snapshot,
    standard_pricing,
    transition_for,
)

DEPRECATIONS = """
{% table %}
  * Model
  * Release date
  * Shutdown date
  * Recommended replacement

  ---

  * `gemini-2.5-pro`
  * June 17, 2025
  * December 1, 2026
  * `gemini-3.8-flash` (automatically routes to the replacement)
{% /table %}
"""
PRICING = """
## Gemini 3.8 Flash  {% id="gemini-3.8-flash" %}
{% tab title="Standard" %}
  * Input price
  * Free of charge
  * $1

  ---

  * Output price (including thinking tokens)
  * Free of charge
  * $3
{% /tab %}
{% tab title="Batch" %}
  * Input price
  * Not available
  * $1
{% /tab %}
"""


class GeminiModelNoticeTests(unittest.TestCase):
    def test_configured_model_uses_repo_override_or_pipeline_fallback(self):
        workflow = "GEMINI_MODEL: ${{ vars.GEMINI_MODEL || 'gemini-2.5-pro' }}"
        self.assertEqual(pipeline_model(workflow, ""), "gemini-2.5-pro")
        self.assertEqual(pipeline_model(workflow, "gemini-3.8-flash"), "gemini-3.8-flash")
        with self.assertRaises(ValueError):
            pipeline_model(workflow, "gemini-1?api_key=invalid")

    def test_detects_public_replacement_and_standard_free_tier(self):
        self.assertEqual(transition_for(DEPRECATIONS, "gemini-2.5-pro"),
                         {"date": "December 1, 2026", "replacement": "gemini-3.8-flash"})
        self.assertIsNone(transition_for(DEPRECATIONS, "gemini-2.5"))
        self.assertEqual(standard_pricing(PRICING, "gemini-3.8-flash"), {"free": "listed"})
        self.assertEqual(standard_pricing(PRICING.replace("Free of charge", "Not available"),
                                          "gemini-3.8-flash"), {"free": "unavailable"})

    def test_sends_only_when_state_changes_or_first_check_is_actionable(self):
        active = snapshot("gemini-2.5-pro", DEPRECATIONS, PRICING, "HTTP 200")
        self.assertTrue(needs_notice(None, active))
        self.assertFalse(needs_notice(active, active))
        self.assertIn("gemini-3.8-flash", mail_message(None, active))
        replacement = snapshot("gemini-3.8-flash", DEPRECATIONS, PRICING, "HTTP 200")
        self.assertFalse(needs_notice(None, replacement))
        self.assertTrue(needs_notice(active, replacement))
        self.assertTrue(needs_notice(replacement, {**replacement, "access": "HTTP 403"}))

    def test_alerts_once_when_published_transition_date_arrives(self):
        first = snapshot("gemini-2.5-pro", DEPRECATIONS, PRICING, "HTTP 200", date(2026, 11, 30))
        second = snapshot("gemini-2.5-pro", DEPRECATIONS, PRICING, "HTTP 200", date(2026, 12, 1))
        self.assertFalse(first["transition"]["date_reached"])
        self.assertTrue(second["transition"]["date_reached"])
        self.assertTrue(needs_notice(first, second))
        self.assertFalse(needs_notice(second, second))


if __name__ == "__main__":
    unittest.main()
