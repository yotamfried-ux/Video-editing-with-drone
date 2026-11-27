from types import SimpleNamespace
from unittest.mock import patch

import pytest

from config import settings
from integrations import gemini


def test_default_gemini_model_is_free_tier_compatible(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert settings.GEMINI_MODEL == "gemini-2.5-flash"


def test_zero_quota_falls_back_to_gemini_2_5_flash():
    calls = []

    class FakeModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"] == "gemini-3.1-pro-preview":
                raise RuntimeError(
                    "429 RESOURCE_EXHAUSTED: Quota exceeded for metric: "
                    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0"
                )
            return SimpleNamespace(text="ok", usage_metadata=None)

    fake_client = SimpleNamespace(models=FakeModels())
    model = gemini._Model("gemini-3.1-pro-preview")

    with (
        patch.object(gemini, "_get_client", return_value=fake_client),
        patch("integrations.qualification.check_llm_budget"),
        patch.object(gemini.llm_cost, "record_call") as record_call,
    ):
        resp = model.generate_content("hello")

    assert resp.text == "ok"
    assert calls == ["gemini-3.1-pro-preview", "gemini-2.5-flash"]
    record_call.assert_called_once()
    assert record_call.call_args.kwargs["model"] == "gemini-2.5-flash"


def test_non_zero_quota_error_is_not_swallowed():
    class FakeModels:
        def generate_content(self, **kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED: rate limit per minute exceeded")

    fake_client = SimpleNamespace(models=FakeModels())
    model = gemini._Model("gemini-3.1-pro-preview")

    with (
        patch.object(gemini, "_get_client", return_value=fake_client),
        patch("integrations.qualification.check_llm_budget"),
        pytest.raises(RuntimeError, match="rate limit per minute exceeded"),
    ):
        model.generate_content("hello")
