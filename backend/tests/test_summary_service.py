"""
Tests for app/services/summary_service.py — OpenAI client construction.
"""
import app.services.summary_service as summary_service
from app.core.config import settings


def test_get_openai_client_sets_bounded_timeout(monkeypatch):
    captured_kwargs = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(summary_service, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(summary_service, "_client", None)

    summary_service.get_openai_client()

    assert captured_kwargs.get("timeout") == settings.openai_timeout_seconds
    assert captured_kwargs["timeout"] is not None
