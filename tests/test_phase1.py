"""
Phase 1 Tests - Environment Setup & Core Abstractions
Tests the LLMProviderFactory for correct model instantiation.
"""
import pytest
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.providers import LLMProviderFactory


class TestLLMProviderFactory:
    """Tests for the LLM Provider Factory."""

    def test_ollama_provider_creates_correct_type(self):
        """Ollama provider should return a ChatOllama instance."""
        from langchain_community.chat_models import ChatOllama
        model = LLMProviderFactory.create_model("ollama", "llama3")
        assert isinstance(model, ChatOllama)
        assert model.model == "llama3"

    def test_ollama_provider_case_insensitive(self):
        """Provider name should be case-insensitive."""
        from langchain_community.chat_models import ChatOllama
        model = LLMProviderFactory.create_model("Ollama", "llama3")
        assert isinstance(model, ChatOllama)

    def test_mock_provider_creates_fake_model(self):
        """Mock provider should return a FakeListChatModel."""
        from langchain_community.chat_models import FakeListChatModel
        model = LLMProviderFactory.create_model("mock", "fake", responses=["Hello!"])
        assert isinstance(model, FakeListChatModel)

    def test_mock_provider_returns_expected_response(self):
        """Mock provider should return the configured response."""
        model = LLMProviderFactory.create_model("mock", "fake", responses=["Test response"])
        result = model.invoke("any question")
        assert "Test response" in result.content

    def test_unsupported_provider_raises_value_error(self):
        """An unsupported provider should raise a ValueError."""
        with pytest.raises(ValueError, match="Unsupported provider"):
            LLMProviderFactory.create_model("invalid_provider", "model")

    def test_supported_providers_list(self):
        """The SUPPORTED_PROVIDERS list should contain the expected providers."""
        expected = ["ollama", "openai", "anthropic", "groq", "gemini", "mock"]
        assert LLMProviderFactory.SUPPORTED_PROVIDERS == expected
