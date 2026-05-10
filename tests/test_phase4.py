"""
Phase 4 Tests - LangGraph Orchestrator & Agents
Uses the mock LLM provider to test without needing a real model.
"""
import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.orchestrator import (
    AgentState,
    classify_intent,
    run_summary_agent,
    run_suggestion_agent,
    run_modification_agent,
    build_graph,
)
from backend.providers import LLMProviderFactory


def _make_state(message: str = "Summarize this document", intent: str = None) -> AgentState:
    """Helper to create a test AgentState."""
    return AgentState(
        user_message=message,
        retrieved_chunks=["The document talks about machine learning and AI."],
        conversation_history=[],
        provider="mock",
        model="fake",
        intent=intent,
        response=None,
    )


class TestIntentClassifier:
    """Tests for the intent classification node."""

    def test_classify_summary(self):
        llm = LLMProviderFactory.create_model("mock", "fake", responses=["summary"])
        state = _make_state("Give me a summary of this document")
        result = classify_intent(state, llm)
        assert result["intent"] == "summary"

    def test_classify_suggestion(self):
        llm = LLMProviderFactory.create_model("mock", "fake", responses=["suggestion"])
        state = _make_state("What improvements can be made?")
        result = classify_intent(state, llm)
        assert result["intent"] == "suggestion"

    def test_classify_modification(self):
        llm = LLMProviderFactory.create_model("mock", "fake", responses=["modification"])
        state = _make_state("Rewrite the introduction paragraph")
        result = classify_intent(state, llm)
        assert result["intent"] == "modification"

    def test_classify_fallback_to_summary(self):
        llm = LLMProviderFactory.create_model("mock", "fake", responses=["unknown_intent"])
        state = _make_state("Hello there")
        result = classify_intent(state, llm)
        assert result["intent"] == "summary"  # default fallback


class TestSpecialistAgents:
    """Tests for the specialist agent runners."""

    def test_summary_agent_returns_response(self):
        llm = LLMProviderFactory.create_model("mock", "fake", responses=["Here is the summary."])
        state = _make_state("Summarize this")
        result = run_summary_agent(state, llm)
        assert result["response"] == "Here is the summary."

    def test_suggestion_agent_returns_response(self):
        llm = LLMProviderFactory.create_model("mock", "fake", responses=["Here are my suggestions."])
        state = _make_state("What can be improved?")
        result = run_suggestion_agent(state, llm)
        assert result["response"] == "Here are my suggestions."

    def test_modification_agent_returns_response(self):
        llm = LLMProviderFactory.create_model("mock", "fake", responses=["Here is the modified text."])
        state = _make_state("Rewrite the intro")
        result = run_modification_agent(state, llm)
        assert result["response"] == "Here is the modified text."

    def test_agent_includes_context(self):
        """Agent should process without errors even with context and history."""
        llm = LLMProviderFactory.create_model("mock", "fake", responses=["Response with context."])
        state = AgentState(
            user_message="Explain this",
            retrieved_chunks=["Chunk 1 about AI.", "Chunk 2 about ML."],
            conversation_history=[
                {"role": "user", "content": "Previous question"},
                {"role": "assistant", "content": "Previous answer"},
            ],
            provider="mock",
            model="fake",
            intent="summary",
            response=None,
        )
        result = run_summary_agent(state, llm)
        assert result["response"] == "Response with context."


class TestGraphExecution:
    """Tests for the full LangGraph state graph."""

    def test_graph_routes_to_summary(self):
        # First response for classifier, second for the agent
        llm = LLMProviderFactory.create_model(
            "mock", "fake",
            responses=["summary", "This is the document summary."]
        )
        graph = build_graph(llm)
        state = _make_state("Summarize the document")
        result = graph.invoke(state)
        assert result["intent"] == "summary"
        assert result["response"] == "This is the document summary."

    def test_graph_routes_to_suggestion(self):
        llm = LLMProviderFactory.create_model(
            "mock", "fake",
            responses=["suggestion", "Here are my suggestions."]
        )
        graph = build_graph(llm)
        state = _make_state("What improvements can be made?")
        result = graph.invoke(state)
        assert result["intent"] == "suggestion"
        assert result["response"] == "Here are my suggestions."

    def test_graph_routes_to_modification(self):
        llm = LLMProviderFactory.create_model(
            "mock", "fake",
            responses=["modification", "Here is the rewritten text."]
        )
        graph = build_graph(llm)
        state = _make_state("Rewrite this section")
        result = graph.invoke(state)
        assert result["intent"] == "modification"
        assert result["response"] == "Here is the rewritten text."
