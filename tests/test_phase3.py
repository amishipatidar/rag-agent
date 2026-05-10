"""
Phase 3 Tests - SQLite History & Memory
"""
import pytest
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.database import (
    init_db,
    create_conversation,
    save_message,
    get_conversation_history,
    get_context_messages,
    list_conversations,
)


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database for each test."""
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


class TestDatabaseInit:
    """Tests for database initialization."""

    def test_init_creates_db_file(self, tmp_path):
        path = str(tmp_path / "new.db")
        assert not os.path.exists(path)
        init_db(path)
        assert os.path.exists(path)

    def test_init_idempotent(self, db_path):
        """Calling init_db twice should not raise errors."""
        init_db(db_path)  # second call
        convs = list_conversations(db_path)
        assert isinstance(convs, list)


class TestConversations:
    """Tests for conversation CRUD."""

    def test_create_conversation(self, db_path):
        conv_id = create_conversation("Test Chat", db_path)
        assert isinstance(conv_id, int)
        assert conv_id > 0

    def test_list_conversations(self, db_path):
        create_conversation("Chat 1", db_path)
        create_conversation("Chat 2", db_path)
        convs = list_conversations(db_path)
        assert len(convs) == 2
        # Most recent first
        assert convs[0]["title"] == "Chat 2"

    def test_conversation_has_timestamps(self, db_path):
        create_conversation("Timestamped", db_path)
        convs = list_conversations(db_path)
        assert convs[0]["created_at"] is not None
        assert convs[0]["updated_at"] is not None


class TestMessages:
    """Tests for message saving and retrieval."""

    def test_save_and_retrieve_message(self, db_path):
        conv_id = create_conversation("Test", db_path)
        save_message(conv_id, "user", "Hello!", db_path=db_path)
        save_message(conv_id, "assistant", "Hi there!", provider="ollama", model="llama3", agent_type="summary", db_path=db_path)

        history = get_conversation_history(conv_id, db_path=db_path)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello!"
        assert history[1]["role"] == "assistant"
        assert history[1]["provider"] == "ollama"
        assert history[1]["model"] == "llama3"
        assert history[1]["agent_type"] == "summary"

    def test_get_last_n_messages(self, db_path):
        conv_id = create_conversation("Test", db_path)
        for i in range(10):
            save_message(conv_id, "user", f"Message {i}", db_path=db_path)

        history = get_conversation_history(conv_id, last_n=3, db_path=db_path)
        assert len(history) == 3
        # Should be the last 3 in chronological order
        assert history[0]["content"] == "Message 7"
        assert history[1]["content"] == "Message 8"
        assert history[2]["content"] == "Message 9"

    def test_get_context_messages_format(self, db_path):
        conv_id = create_conversation("Test", db_path)
        save_message(conv_id, "user", "What is AI?", db_path=db_path)
        save_message(conv_id, "assistant", "AI is artificial intelligence.", provider="ollama", model="llama3", db_path=db_path)

        context = get_context_messages(conv_id, last_n=10, db_path=db_path)
        assert len(context) == 2
        # Should only have role and content (LangChain compatible)
        assert set(context[0].keys()) == {"role", "content"}
        assert context[0]["role"] == "user"
        assert context[1]["role"] == "assistant"

    def test_messages_isolated_per_conversation(self, db_path):
        conv1 = create_conversation("Chat 1", db_path)
        conv2 = create_conversation("Chat 2", db_path)
        save_message(conv1, "user", "In chat 1", db_path=db_path)
        save_message(conv2, "user", "In chat 2", db_path=db_path)

        h1 = get_conversation_history(conv1, db_path=db_path)
        h2 = get_conversation_history(conv2, db_path=db_path)
        assert len(h1) == 1
        assert len(h2) == 1
        assert h1[0]["content"] == "In chat 1"
        assert h2[0]["content"] == "In chat 2"

    def test_empty_conversation_returns_empty_list(self, db_path):
        conv_id = create_conversation("Empty", db_path)
        history = get_conversation_history(conv_id, db_path=db_path)
        assert history == []
