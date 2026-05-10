"""
Langfuse Tracing - Observability for RAGgent.
Provides trace/span helpers for monitoring LLM calls, intent classification, and agent responses.
"""
import os
from typing import Optional
from contextlib import contextmanager


def _get_langfuse_client():
    """
    Initialize and return a Langfuse client using environment variables.
    Returns None if Langfuse is not configured.
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST")

    if not public_key or not secret_key:
        return None

    try:
        from langfuse import Langfuse
        return Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
    except Exception:
        return None


# Lazy singleton
_langfuse = None


def get_langfuse():
    """Get or create the singleton Langfuse client."""
    global _langfuse
    if _langfuse is None:
        _langfuse = _get_langfuse_client()
    return _langfuse


def get_langfuse_callback():
    """
    Get a LangChain callback handler for Langfuse tracing.
    Returns None if Langfuse is not configured or callback not available.
    """
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip('"')
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip('"')
    host = (os.getenv("LANGFUSE_BASE_URL", "").strip('"') or 
            os.getenv("LANGFUSE_HOST", "").strip('"'))

    if not public_key or not secret_key:
        return None

    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception as e:
        print(f"[Langfuse] Callback handler not available: {e}")
        return None


def create_trace(name: str, metadata: Optional[dict] = None, user_id: Optional[str] = None):
    """
    Create a new Langfuse trace for a user interaction.

    Args:
        name: Name of the trace (e.g., 'chat', 'upload').
        metadata: Optional metadata dict.
        user_id: Optional user identifier.

    Returns:
        A Langfuse trace object, or None if Langfuse is not configured.
    """
    client = get_langfuse()
    if client is None:
        return None

    try:
        return client.trace(
            name=name,
            metadata=metadata or {},
            user_id=user_id,
        )
    except Exception:
        return None


def flush():
    """Flush any pending Langfuse events."""
    client = get_langfuse()
    if client:
        try:
            client.flush()
        except Exception:
            pass
