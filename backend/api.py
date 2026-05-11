"""
FastAPI Backend - REST API for the RAG Agent chatbot.
Endpoints: /upload, /chat, /models, /conversations
"""
import os
from dotenv import load_dotenv
load_dotenv()  # Load .env file
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, List

from backend.database import (
    init_db, create_conversation, save_message,
    get_conversation_history, get_context_messages, list_conversations,
    create_user, get_user_by_email
)
from backend.providers import LLMProviderFactory
from backend.rag_pipeline import FAISSIndex, chunk_text, embed_texts, ingest_document, search_faiss
from backend.orchestrator import AgentState, build_graph
from backend.tracing import get_langfuse_callback, create_trace, flush as langfuse_flush
from backend.auth import hash_password, verify_password, create_access_token, get_current_user
from fastapi import Depends

# ── App Setup ─────────────────────────────────────────────────────────────

app = FastAPI(title="RAG Agent", version="1.0.0")

# Initialize database on startup
init_db()

# Global FAISS index (per-session, in-memory)
_faiss_index: Optional[FAISSIndex] = None
_uploaded_filename: Optional[str] = None
_uploaded_text: Optional[str] = None

# Thread pool for CPU-bound work (embeddings, LLM calls)
_executor = ThreadPoolExecutor(max_workers=2)

# Static files
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uploads")
FAISS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "faiss_index")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(FAISS_DIR, exist_ok=True)

# Load persisted FAISS index on startup (if it exists)
try:
    _persisted_index = FAISSIndex()
    _persisted_index.load(FAISS_DIR)
    _faiss_index = _persisted_index
    _uploaded_filename = "(restored from disk)"
except Exception:
    pass  # No saved index yet — that's fine


# ── Request/Response Models ──────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    provider: str = "ollama"
    model: str = "llama3"
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
    current_user: dict = Depends(get_current_user)
):
    """Upload and index a document (.docx, .xlsx, .pdf) via multipart form upload."""
    global _faiss_index, _uploaded_filename, _uploaded_text

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".docx", ".xlsx", ".pdf"]:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    # Save uploaded file to disk
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    try:
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {str(e)}")

    # Ingest and index (run in thread pool to avoid blocking async loop)
    loop = asyncio.get_event_loop()
    try:
        _faiss_index, _uploaded_text = await loop.run_in_executor(_executor, ingest_document, file_path)
        _uploaded_filename = file.filename
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")

    # Persist the FAISS index to disk so it survives server restarts
    try:
        await loop.run_in_executor(_executor, lambda: _faiss_index.save(FAISS_DIR))
    except Exception as e:
        print(f"[Warning] Failed to save FAISS index: {e}")

    chunks = _faiss_index.index.ntotal if _faiss_index and _faiss_index.index else 0

    return {
        "status": "success",
        "filename": file.filename,
        "chunks_indexed": chunks,
        "message": "Document indexed successfully" if chunks > 0 else "Document uploaded but no text was extracted. Try a different file.",
    }

@app.get("/api/document", response_model=DocumentResponse)
async def get_document(current_user: dict = Depends(get_current_user)):
    """Get the currently loaded document text."""
    if not _uploaded_text:
        raise HTTPException(status_code=404, detail="No document loaded")
    return DocumentResponse(text=_uploaded_text)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Send a message and get a response from the AI agents."""
    global _faiss_index

    # Create or use existing conversation
    conv_id = request.conversation_id
    if not conv_id:
        conv_id = create_conversation(user_id=current_user["id"])

    # Save user message
    save_message(conv_id, "user", request.message)

    # Retrieve relevant chunks — top_k=3 for faster LLM processing
    chunks = []
    if _faiss_index:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            _executor, lambda: search_faiss(_faiss_index, request.message, top_k=3)
        )
        chunks = [chunk for chunk, _ in results]

    # Get conversation history for context
    history = get_context_messages(conv_id, last_n=10)

    # Create Langfuse trace for this interaction
    trace = create_trace(
        name="chat",
        metadata={
            "provider": request.provider,
            "model": request.model,
            "has_document": bool(chunks),
            "chunks_retrieved": len(chunks),
        },
    )

    # Build LLM with Langfuse callback + hyperparameter tuning for speed
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

    graph = build_graph(llm)

    # Run the graph
    state = AgentState(
        user_message=request.message,
        retrieved_chunks=chunks,
        conversation_history=history,
        provider=request.provider,
        model=request.model,
        intent=None,
        response=None,
    )

    # Run graph in thread pool (LLM calls are blocking)
    import time
    start_time = time.time()
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(_executor, graph.invoke, state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")
    latency_ms = int((time.time() - start_time) * 1000)

    # Save assistant response
    save_message(
        conv_id, "assistant", result["response"],
        provider=request.provider, model=request.model,
        agent_type=result.get("intent")
    )

    # Flush Langfuse events
    langfuse_flush()

    return ChatResponse(
        response=result["response"],
        intent=result.get("intent", "unknown"),
        provider=request.provider,
        model=request.model,
        conversation_id=conv_id,
        latency_ms=latency_ms,
    )


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    Stream a chat response token-by-token using Server-Sent Events (SSE).
    1. Intent is classified first (non-streamed, fast).
    2. The specialist agent then streams tokens back to the frontend.
    """
    global _faiss_index

    # Create or use existing conversation
    conv_id = request.conversation_id
    if not conv_id:
        conv_id = create_conversation(user_id=current_user["id"])

    # Save user message
    save_message(conv_id, "user", request.message)

    # Retrieve relevant chunks
    chunks = []
    if _faiss_index:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            _executor, lambda: search_faiss(_faiss_index, request.message, top_k=3)
        )
        chunks = [chunk for chunk, _ in results]

    # Get conversation history
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

    # Step 1: Classify intent (fast, non-streamed)
    from backend.orchestrator import classify_intent, get_agent_messages, SUMMARY_PROMPT, SUGGESTION_PROMPT, MODIFICATION_PROMPT
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    state = AgentState(
        user_message=request.message,
        retrieved_chunks=chunks,
        conversation_history=history,
        provider=request.provider,
        model=request.model,
        intent=None,
        response=None,
    )

    loop = asyncio.get_event_loop()
    classified = await loop.run_in_executor(_executor, classify_intent, state, llm)
    intent = classified["intent"]

    # Select prompt based on intent
    prompt_map = {
        "summary": SUMMARY_PROMPT,
        "suggestion": SUGGESTION_PROMPT,
        "modification": MODIFICATION_PROMPT,
    }
    system_prompt = prompt_map.get(intent, SUMMARY_PROMPT)

    # Build messages for the specialist agent
    messages = get_agent_messages(classified, system_prompt)

    # Step 2: Stream the specialist agent response
    async def event_generator():
        import time
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
            yield f"data: {{\"type\": \"error\", \"detail\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/api/models")
async def get_models():
    """Get available models from Ollama and list external providers."""
    models = {
        "ollama": [],
        "external": ["openai", "gemini"],
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


@app.get("/api/conversations")
async def get_conversations(current_user: dict = Depends(get_current_user)):
    """List conversations belonging to the current user."""
    return list_conversations(user_id=current_user["id"])


@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int, current_user: dict = Depends(get_current_user)):
    """Get messages for a conversation."""
    return get_conversation_history(conversation_id)


@app.get("/api/status")
async def status(current_user: dict = Depends(get_current_user)):
    """Health check and current state."""
    return {
        "status": "running",
        "user": current_user["email"],
        "document_loaded": _uploaded_filename,
        "chunks_indexed": _faiss_index.index.ntotal if _faiss_index and _faiss_index.index else 0,
    }


# ── Serve Frontend ────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Public health check for Railway/Render deployment."""
    return {"status": "ok"}


@app.get("/")
async def serve_index():
    """Serve the main frontend page."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# Mount static files AFTER API routes
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
