"""
SQLite History & Memory - Persistence layer for conversation tracking.
Stores per-turn messages with provider/model metadata.
"""
import sqlite3
import os
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ragflow.db")


def _get_connection(db_path: str = None) -> sqlite3.Connection:
    """Get a SQLite connection, creating the database if needed."""
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = None) -> None:
    """
    Initialize the database schema.
    Creates tables if they don't already exist.

    Args:
        db_path: Optional custom path to the database file.
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            hashed_password TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT DEFAULT 'New Conversation',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
            content TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            agent_type TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


def create_user(email: str, hashed_password: str, db_path: str = None) -> int:
    """
    Create a new user and return their ID.

    Args:
        email: User's email address (must be unique).
        hashed_password: Bcrypt-hashed password string.
        db_path: Optional custom database path.

    Returns:
        The new user's ID.

    Raises:
        ValueError: If email already exists.
    """
    conn = _get_connection(db_path)
    now = datetime.now(tz=timezone.utc).isoformat()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (email, hashed_password, created_at) VALUES (?, ?, ?)",
            (email, hashed_password, now)
        )
        user_id = cursor.lastrowid
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        raise ValueError(f"Email already registered: {email}")
    finally:
        conn.close()


def get_user_by_email(email: str, db_path: str = None) -> Optional[Dict]:
    """
    Fetch a user record by email.

    Args:
        email: The email to look up.
        db_path: Optional custom database path.

    Returns:
        A dict with id, email, hashed_password, created_at — or None if not found.
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, email, hashed_password, created_at FROM users WHERE email = ?",
        (email,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int, db_path: str = None) -> Optional[Dict]:
    """
    Fetch a user record by ID.

    Args:
        user_id: The user's primary key.
        db_path: Optional custom database path.

    Returns:
        A dict with id, email, created_at — or None if not found.
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, email, created_at FROM users WHERE id = ?",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def create_conversation(title: str = "New Conversation", user_id: int = None, db_path: str = None) -> int:
    """
    Create a new conversation and return its ID.

    Args:
        title: Title for the conversation.
        db_path: Optional custom database path.

    Returns:
        The new conversation's ID.
    """
    conn = _get_connection(db_path)
    now = datetime.now(tz=timezone.utc).isoformat()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, title, now, now)
    )
    conv_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return conv_id


def save_message(
    conversation_id: int,
    role: str,
    content: str,
    provider: str = None,
    model: str = None,
    agent_type: str = None,
    db_path: str = None
) -> int:
    """
    Save a message to the database.

    Args:
        conversation_id: The conversation this message belongs to.
        role: 'user', 'assistant', or 'system'.
        content: The message text.
        provider: LLM provider used (e.g., 'ollama', 'openai').
        model: Model name used (e.g., 'llama3', 'gpt-4o').
        agent_type: Which agent handled this (e.g., 'summary', 'suggestion', 'modification').
        db_path: Optional custom database path.

    Returns:
        The new message's ID.
    """
    conn = _get_connection(db_path)
    now = datetime.now(tz=timezone.utc).isoformat()
    cursor = conn.cursor()

    cursor.execute(
        """INSERT INTO messages 
           (conversation_id, role, content, provider, model, agent_type, created_at) 
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (conversation_id, role, content, provider, model, agent_type, now)
    )
    msg_id = cursor.lastrowid

    # Update conversation's updated_at
    cursor.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (now, conversation_id)
    )

    conn.commit()
    conn.close()
    return msg_id


def get_conversation_history(
    conversation_id: int,
    last_n: int = None,
    db_path: str = None
) -> List[Dict]:
    """
    Retrieve messages for a conversation.

    Args:
        conversation_id: The conversation to fetch.
        last_n: If set, return only the last N messages.
        db_path: Optional custom database path.

    Returns:
        List of message dicts with keys: role, content, provider, model, agent_type, created_at.
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()

    if last_n:
        cursor.execute(
            """SELECT role, content, provider, model, agent_type, created_at 
               FROM messages 
               WHERE conversation_id = ? 
               ORDER BY id DESC LIMIT ?""",
            (conversation_id, last_n)
        )
        rows = cursor.fetchall()
        rows.reverse()  # Return in chronological order
    else:
        cursor.execute(
            """SELECT role, content, provider, model, agent_type, created_at 
               FROM messages 
               WHERE conversation_id = ? 
               ORDER BY id ASC""",
            (conversation_id,)
        )
        rows = cursor.fetchall()

    conn.close()
    return [dict(row) for row in rows]


def get_context_messages(conversation_id: int, last_n: int = 10, db_path: str = None) -> List[Dict]:
    """
    Get the last N messages formatted for LLM context injection.

    Args:
        conversation_id: The conversation to fetch.
        last_n: Number of recent messages to include.
        db_path: Optional custom database path.

    Returns:
        List of dicts with 'role' and 'content' keys (compatible with LangChain message format).
    """
    history = get_conversation_history(conversation_id, last_n=last_n, db_path=db_path)
    return [{"role": msg["role"], "content": msg["content"]} for msg in history]


def list_conversations(user_id: int = None, db_path: str = None) -> List[Dict]:
    """
    List conversations, filtered by user_id if provided.

    Args:
        user_id: If provided, only return conversations for this user.
        db_path: Optional custom database path.

    Returns:
        List of conversation dicts with keys: id, title, created_at, updated_at.
    """
    conn = _get_connection(db_path)
    cursor = conn.cursor()
    if user_id is not None:
        cursor.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,)
        )
    else:
        # Legacy: return all conversations (for backward compat)
        cursor.execute("SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
