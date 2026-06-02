"""
FastAPI Backend - REST API for the RAG Agent chatbot.
Endpoints: /upload, /chat, /models, /conversations
Commands: /help, /status, /clear, /chat, /summary, /suggest, /modify
"""
import os
import json
import time
import asyncio
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Dict

import httpx
from dotenv import load_dotenv
load_dotenv()  # Load .env file

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from backend.database import (
    init_db, create_conversation, save_message,
    get_conversation_history, get_context_messages, list_conversations,
    create_user, get_user_by_email, delete_conversation
)
from backend.providers import LLMProviderFactory
from backend.rag_pipeline import FAISSIndex, chunk_text, embed_texts, ingest_document, search_faiss
from backend.orchestrator import AgentState, build_graph
from backend.tracing import get_langfuse_callback, create_trace, flush as langfuse_flush
from backend.auth import hash_password, verify_password, create_access_token, get_current_user


# ── App Setup ─────────────────────────────────────────────────────────────

app = FastAPI(title="RAG Agent", version="2.0.0")

# Initialize database on startup
init_db()

# Thread pool for CPU-bound work (embeddings, LLM calls)
_executor = ThreadPoolExecutor(max_workers=2)

# Static files & directories
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
FAISS_DIR = os.path.join(DATA_DIR, "faiss_index")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(FAISS_DIR, exist_ok=True)


# ── Per-Conversation Session Manager ─────────────────────────────────────────────

@dataclass
class ConversationSession:
    """Holds per-conversation document and FAISS index state."""
    faiss_index: Optional[FAISSIndex] = None
    uploaded_filename: Optional[str] = None
    uploaded_text: Optional[str] = None


# In-memory store: conversation_id (int) -> ConversationSession
_conversation_sessions: Dict[int, ConversationSession] = {}


def _get_conversation_session(conversation_id: int) -> ConversationSession:
    """Get or create a conversation session, restoring persisted index if available."""
    if conversation_id not in _conversation_sessions:
        session = ConversationSession()
        # Try to restore persisted FAISS index for this conversation
        conv_faiss_dir = os.path.join(FAISS_DIR, f"conv_{conversation_id}")
        conv_text_path = os.path.join(conv_faiss_dir, "document_text.json")
        try:
            idx = FAISSIndex()
            idx.load(conv_faiss_dir)
            session.faiss_index = idx
            session.uploaded_filename = "(restored from disk)"
            if os.path.exists(conv_text_path):
                with open(conv_text_path, "r", encoding="utf-8") as f:
                    session.uploaded_text = json.load(f)
        except Exception:
            pass  # No saved index for this conversation yet
        _conversation_sessions[conversation_id] = session
    return _conversation_sessions[conversation_id]


def _get_conversation_faiss_dir(conversation_id: int) -> str:
    """Return the conversation-specific FAISS directory, creating it if needed."""
    d = os.path.join(FAISS_DIR, f"conv_{conversation_id}")
    os.makedirs(d, exist_ok=True)
    return d


def _get_conversation_upload_dir(conversation_id: int) -> str:
    """Return the conversation-specific upload directory, creating it if needed."""
    d = os.path.join(UPLOAD_DIR, f"conv_{conversation_id}")
    os.makedirs(d, exist_ok=True)
    return d


# ── Slash Command Definitions ────────────────────────────────────────────

HELP_RESPONSE = """## Command Activation

RAG Agent supports **slash commands** for direct control over the AI pipeline.
Type `/` in the chat to see the autocomplete menu.

| Command | Description |
|---------|-------------|
| `/summary <query>` | Bypass intent classifier → route directly to **Summary Agent** |
| `/suggest <query>` | Bypass intent classifier → route directly to **Suggestion Agent** |
| `/modify <query>` | Bypass intent classifier → route directly to **Modification Agent** |
| `/chat <query>` | **General conversation** — no document context injected |
| `/status` | Show loaded document info and RAG index statistics |
| `/help` | Show this command reference |
| `/clear` | Clear current conversation history |

### Tips
- Without a slash command, queries are **auto-routed** by the Intent Classifier.
- A document **must be uploaded** before using `/summary`, `/suggest`, or `/modify`.
- Use `/chat` to talk freely without needing a document.
"""

COMMANDS = {
    "/help": {"description": "Show command reference", "icon": "?", "agent": "system"},
    "/status": {"description": "Document & index status", "icon": "i", "agent": "system"},
    "/clear": {"description": "Clear conversation", "icon": "×", "agent": "system"},
    "/chat": {"description": "General conversation (no document needed)", "icon": "›", "agent": "general"},
    "/summary": {"description": "Route to Summary Agent", "icon": "Σ", "agent": "summary"},
    "/suggest": {"description": "Route to Suggestion Agent", "icon": "*", "agent": "suggestion"},
    "/modify": {"description": "Route to Modification Agent", "icon": "/", "agent": "modification"},
}


def _parse_command(message: str):
    """
    Parse a slash command from a message.
    Returns (command_name, query_body) or (None, message) if not a command.
    """
    stripped = message.strip()
    if not stripped.startswith("/"):
        return None, message
    parts = stripped.split(None, 1)
    cmd = parts[0].lower()
    body = parts[1] if len(parts) > 1 else ""
    if cmd in COMMANDS:
        return cmd, body
    return None, message


# ── Request/Response Models ──────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    conversation_id: Optional[int] = None


class ChatResponse(BaseModel):
    response: str
    intent: str
    provider: str
    model: str
    conversation_id: int
    latency_ms: int


class DocumentResponse(BaseModel):
    text: str


class UploadRequest(BaseModel):
    filename: str
    data: str  # kept for backward compat — not used by new multipart endpoint


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


# ── Auth Endpoints (public — no token required) ───────────────────────────

@app.post("/api/auth/register")
async def register(request: RegisterRequest):
    """Register a new user and return a JWT token."""
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    if len(request.password.encode('utf-8')) > 72:
        raise HTTPException(status_code=400, detail="Password must be 72 characters or fewer.")

    try:
        hashed = hash_password(request.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        user_id = create_user(email=request.email, hashed_password=hashed)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    token = create_access_token({"sub": str(user_id)})
    return {"access_token": token, "token_type": "bearer", "email": request.email}


@app.post("/api/auth/login")
async def login(request: LoginRequest):
    """Authenticate a user and return a JWT token."""
    user = get_user_by_email(request.email)
    if not user or not verify_password(request.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = create_access_token({"sub": str(user["id"])})
    return {"access_token": token, "token_type": "bearer", "email": user["email"]}


@app.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Return the currently authenticated user's info."""
    return {"id": current_user["id"], "email": current_user["email"], "created_at": current_user["created_at"]}


# ── API Endpoints ─────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...),
    conversation_id: int = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """Upload and index a document (.docx, .xlsx, .pdf) via multipart form upload."""
    if not conversation_id:
        # Create a new conversation if one doesn't exist
        conversation_id = create_conversation(title=file.filename, user_id=current_user["id"])
        
    user_id = current_user["id"]
    session = _get_conversation_session(conversation_id)

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".docx", ".xlsx", ".pdf"]:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    # Save uploaded file to conversation-specific directory
    conv_upload_dir = _get_conversation_upload_dir(conversation_id)
    file_path = os.path.join(conv_upload_dir, file.filename)
    try:
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {str(e)}")

    # Ingest and index (run in thread pool to avoid blocking async loop)
    loop = asyncio.get_event_loop()
    try:
        faiss_index, uploaded_text = await loop.run_in_executor(_executor, ingest_document, file_path)
        session.faiss_index = faiss_index
        session.uploaded_filename = file.filename
        session.uploaded_text = uploaded_text

        # Persist index to disk
        user_faiss_dir = _get_conversation_faiss_dir(conversation_id)
        await loop.run_in_executor(_executor, lambda: faiss_index.save(user_faiss_dir))

        # Save uploaded text to disk
        user_text_path = os.path.join(user_faiss_dir, "document_text.json")
        with open(user_text_path, "w", encoding="utf-8") as f:
            json.dump(uploaded_text, f, ensure_ascii=False)
            
        # Update conversation in DB
        from backend.database import update_conversation_filename
        update_conversation_filename(conversation_id, file.filename)
    except Exception as e:
        print(f"[Warning] Failed to save FAISS index for conversation {conversation_id}: {e}")

    chunks = faiss_index.index.ntotal if faiss_index and faiss_index.index else 0

    return {
        "status": "success",
        "filename": file.filename,
        "conversation_id": conversation_id,
        "chunks_indexed": chunks,
        "message": "Document indexed successfully" if chunks > 0 else "Document uploaded but no text was extracted. Try a different file.",
    }


@app.get("/api/document", response_model=DocumentResponse)
async def get_document(conversation_id: int, current_user: dict = Depends(get_current_user)):
    """Get the currently loaded document text for the specified conversation."""
    session = _get_conversation_session(conversation_id)
    if not session.uploaded_text:
        raise HTTPException(status_code=404, detail="No document loaded")
    return DocumentResponse(text=session.uploaded_text)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    Stream a chat response token-by-token using Server-Sent Events (SSE).
    Supports slash commands for direct agent routing and system actions.
    """
    user_id = current_user["id"]

    # Parse slash command
    command, query_body = _parse_command(request.message)

    # Create or use existing conversation
    conv_id = request.conversation_id
    if not conv_id:
        title = request.message[:30] + "..." if len(request.message) > 30 else request.message
        conv_id = create_conversation(title=title, user_id=user_id)

    # Now that we have conv_id, load the conversation's FAISS session
    session = _get_conversation_session(conv_id)

    # Save user message
    save_message(conv_id, "user", request.message)

    # ── Handle system commands (no LLM needed) ──────────────────────────
    if command == "/help":
        save_message(conv_id, "assistant", HELP_RESPONSE, agent_type="system")
        return _stream_instant_response(HELP_RESPONSE, "system", conv_id, request.provider, request.model)

    if command == "/status":
        chunks_n = session.faiss_index.index.ntotal if session.faiss_index and session.faiss_index.index else 0
        doc_name = session.uploaded_filename or "None"
        status_msg = (
            f"## RAG Agent Status\n\n"
            f"| Property | Value |\n|----------|-------|\n"
            f"| **Document** | {doc_name} |\n"
            f"| **Chunks Indexed** | {chunks_n} |\n"
            f"| **Provider** | {request.provider} |\n"
            f"| **Model** | {request.model} |\n"
            f"| **User** | {current_user['email']} |\n"
        )
        save_message(conv_id, "assistant", status_msg, agent_type="system")
        return _stream_instant_response(status_msg, "system", conv_id, request.provider, request.model)

    if command == "/clear":
        clear_msg = "Conversation cleared."
        save_message(conv_id, "assistant", clear_msg, agent_type="system")
        return _stream_instant_response(clear_msg, "clear", conv_id, request.provider, request.model)

    # ── Determine intent and context strategy ────────────────────────────
    use_document_context = True
    forced_intent = None

    if command == "/chat":
        # General conversation: no document context
        use_document_context = False
        forced_intent = "general"
        effective_message = query_body or request.message
    elif command in ("/summary", "/suggest", "/modify"):
        # Direct agent routing: require document
        if not session.faiss_index or not session.faiss_index.index or session.faiss_index.index.ntotal == 0:
            no_doc_msg = "**No document loaded.** Please upload a document first before using this command.\n\nUse `/chat <message>` for general conversation without a document."
            save_message(conv_id, "assistant", no_doc_msg, agent_type="system")
            return _stream_instant_response(no_doc_msg, "system", conv_id, request.provider, request.model)
        intent_map = {"/summary": "summary", "/suggest": "suggestion", "/modify": "modification"}
        forced_intent = intent_map[command]
        effective_message = query_body or request.message
    else:
        # No command — auto-route, but require document
        if not session.faiss_index or not session.faiss_index.index or session.faiss_index.index.ntotal == 0:
            no_doc_msg = (
                "**No document loaded.** Please upload a document first to use RAG features.\n\n"
                "**Tip:** Use `/chat <message>` for general conversation without a document, "
                "or type `/help` to see all available commands."
            )
            save_message(conv_id, "assistant", no_doc_msg, agent_type="system")
            return _stream_instant_response(no_doc_msg, "system", conv_id, request.provider, request.model)
        effective_message = request.message

    # ── Retrieve chunks if using document context ────────────────────────
    chunks = []
    if use_document_context and session.faiss_index:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            _executor, lambda: search_faiss(session.faiss_index, effective_message, top_k=3)
        )
        chunks = [chunk for chunk, _ in results]

    # Get conversation history for context
    history = get_context_messages(conv_id, last_n=10)

    # Build LLM
    langfuse_cb = get_langfuse_callback()
    try:
        callbacks = [langfuse_cb] if langfuse_cb else []
        llm = LLMProviderFactory.create_model(
            request.provider,
            request.model,
            callbacks=callbacks,
            temperature=0.1,
            max_tokens=300,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to create model: {str(e)}")

    # ── Classify intent or use forced intent ─────────────────────────────
    from backend.orchestrator import classify_intent, get_agent_messages, SUMMARY_PROMPT, SUGGESTION_PROMPT, MODIFICATION_PROMPT
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    state = AgentState(
        user_message=effective_message,
        retrieved_chunks=chunks,
        conversation_history=history,
        provider=request.provider,
        model=request.model,
        intent=forced_intent,
        response=None,
    )

    if forced_intent and forced_intent != "general":
        # Skip classifier — use forced intent
        intent = forced_intent
    elif forced_intent == "general":
        intent = "general"
    else:
        # Auto-classify
        loop = asyncio.get_event_loop()
        classified = await loop.run_in_executor(_executor, classify_intent, state, llm)
        intent = classified["intent"]
        state = {**state, "intent": intent}

    # Select prompt based on intent
    GENERAL_PROMPT = """You are a highly conversational, fun, and engaging AI companion.
You love chatting, making witty observations, and keeping the energy light and entertaining.
CRITICAL RULE: NEVER say "As an AI..." or "I don't have personal feelings...". Act like a fun persona with strong opinions and a lively attitude.
IMPORTANT FORMATTING: Use standard spelling and grammar. Do not drop the 'g' in '-ing' words (e.g., say 'doing' instead of 'doin').
Answer the user's question directly and conversationally. You do not have any document context for this query."""

    prompt_map = {
        "summary": SUMMARY_PROMPT,
        "suggestion": SUGGESTION_PROMPT,
        "modification": MODIFICATION_PROMPT,
        "general": GENERAL_PROMPT,
    }
    system_prompt = prompt_map.get(intent, SUMMARY_PROMPT)

    # Build messages for the specialist agent
    messages = get_agent_messages(state, system_prompt)

    # ── Stream the specialist agent response ─────────────────────────────
    async def event_generator():
        full_response = ""
        start_time = time.time()

        # Send intent immediately so frontend can update routing UI
        yield f"data: {{\"type\": \"intent\", \"intent\": \"{intent}\", \"conversation_id\": {conv_id}}}\n\n"

        try:
            # Stream tokens from LLM
            for chunk in llm.stream(messages):
                token = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if token:
                    full_response += token
                    # Escape token for JSON
                    safe_token = token.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
                    yield f"data: {{\"type\": \"token\", \"token\": \"{safe_token}\"}}\n\n"

            latency_ms = int((time.time() - start_time) * 1000)

            # Save full response to DB
            save_message(
                conv_id, "assistant", full_response,
                provider=request.provider, model=request.model,
                agent_type=intent
            )
            langfuse_flush()

            # Send done event with metadata
            yield f"data: {{\"type\": \"done\", \"latency_ms\": {latency_ms}, \"provider\": \"{request.provider}\", \"model\": \"{request.model}\"}}\n\n"

        except Exception as e:
            error_msg = str(e).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            yield f"data: {{\"type\": \"error\", \"detail\": \"{error_msg}\"}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


def _stream_instant_response(content: str, intent: str, conv_id: int, provider: str, model: str):
    """Helper to stream an instant (non-LLM) response as SSE."""
    async def generator():
        yield f"data: {{\"type\": \"intent\", \"intent\": \"{intent}\", \"conversation_id\": {conv_id}}}\n\n"
        # Send full content as one token
        safe = content.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')
        yield f"data: {{\"type\": \"token\", \"token\": \"{safe}\"}}\n\n"
        yield f"data: {{\"type\": \"done\", \"latency_ms\": 0, \"provider\": \"{provider}\", \"model\": \"{model}\"}}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/models")
async def get_models():
    """Get available models for all providers."""
    models = {
        "ollama": [],
        "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "gemini": ["gemini-2.0-flash", "gemini-2.5-flash-preview-05-20", "gemini-2.5-pro-preview-05-06", "gemini-1.5-pro"],
        "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    }

    # Try fetching Ollama models
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models["ollama"] = [m["name"] for m in data.get("models", [])]
    except Exception:
        models["ollama"] = []

    return models


@app.get("/api/commands")
async def get_commands():
    """Return the list of available slash commands for the frontend autocomplete."""
    return COMMANDS


@app.get("/api/conversations")
async def get_conversations(current_user: dict = Depends(get_current_user)):
    """List conversations belonging to the current user."""
    return list_conversations(user_id=current_user["id"])


@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int, current_user: dict = Depends(get_current_user)):
    """Get messages for a conversation."""
    return get_conversation_history(conversation_id)


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation_api(conversation_id: int, current_user: dict = Depends(get_current_user)):
    """Delete a conversation."""
    success = delete_conversation(conversation_id, user_id=current_user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found or not owned by user.")
    return {"status": "deleted"}


@app.get("/api/status")
async def status(conversation_id: int, current_user: dict = Depends(get_current_user)):
    """Health check and current state."""
    session = _get_conversation_session(conversation_id)
    return {
        "status": "running",
        "user": current_user["email"],
        "document_loaded": session.uploaded_filename,
        "chunks_indexed": session.faiss_index.index.ntotal if session.faiss_index and session.faiss_index.index else 0,
    }


# ── Serve Frontend ────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Public health check for Railway/Render deployment."""
    return {"status": "ok"}


@app.get("/")
async def serve_index():
    """Serve the main frontend page without caching."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})


# Mount static files AFTER API routes
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
