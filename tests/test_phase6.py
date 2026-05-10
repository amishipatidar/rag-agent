"""
Phase 6 Tests - Langfuse Observability
"""
import pytest
import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.tracing import get_langfuse, get_langfuse_callback, create_trace, flush
from backend.providers import LLMProviderFactory


class TestTracingModule:
    """Tests for the Langfuse tracing module."""

    def test_get_langfuse_returns_client_when_configured(self):
        """If env vars are set, Langfuse client should be created."""
        if os.getenv("LANGFUSE_PUBLIC_KEY"):
            client = get_langfuse()
            assert client is not None
        else:
            pytest.skip("Langfuse not configured")

    def test_get_langfuse_callback_returns_handler(self):
        """Callback handler should be returned when Langfuse is configured."""
        if os.getenv("LANGFUSE_PUBLIC_KEY"):
            cb = get_langfuse_callback()
            assert cb is not None
        else:
            pytest.skip("Langfuse not configured")

    def test_get_langfuse_returns_none_without_config(self, monkeypatch):
        """Without env vars, should return None gracefully."""
        import backend.tracing as tracing_module
        # Reset singleton
        tracing_module._langfuse = None
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        client = tracing_module._get_langfuse_client()
        assert client is None

    def test_create_trace_returns_none_without_config(self, monkeypatch):
        """create_trace should return None when Langfuse is not configured."""
        import backend.tracing as tracing_module
        tracing_module._langfuse = None
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        trace = create_trace("test")
        assert trace is None

    def test_flush_does_not_crash_without_config(self, monkeypatch):
        """flush() should not raise even without Langfuse configured."""
        import backend.tracing as tracing_module
        tracing_module._langfuse = None
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        flush()  # Should not raise


class TestProviderCallbacks:
    """Tests for callback integration in providers."""

    def test_mock_provider_accepts_callbacks(self):
        """Mock provider should work with callbacks parameter."""
        llm = LLMProviderFactory.create_model("mock", "fake", callbacks=[], responses=["test"])
        result = llm.invoke("hello")
        assert result.content == "test"

    def test_mock_provider_works_without_callbacks(self):
        """Mock provider should still work without callbacks."""
        llm = LLMProviderFactory.create_model("mock", "fake", responses=["test"])
        result = llm.invoke("hello")
        assert result.content == "test"
