# RAG Agent
> An Enterprise-Grade Multi-Agent RAG Chatbot

![RAGgent](https://img.shields.io/badge/Status-Active-success)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688)
![LangChain](https://img.shields.io/badge/LangChain-Integration-green)

RAG Agent is a powerful, AI chatbot that uses Retrieval-Augmented Generation (RAG) to provide highly context-aware responses based on your documents. Designed for enterprise use, it features a multi-agent architecture to dynamically route user queries to the best specialized agent.

## Key Features
- **Multi-Agent Architecture:** Dynamically routes queries to Specialist Agents (Summary, Suggestion, Modification).
- **Document Ingestion:** Upload PDF, DOCX, and XLSX files to dynamically create a FAISS vector database.
- **Persistent Memory:** SQLite database keeps track of user conversations, agent routing history, and LLM context.
- **Provider Agnostic:** Supports multiple LLM providers (Ollama, OpenAI, Groq, Google Gemini).
- **Enterprise UI:** Professional, responsive web interface with live routing workflow indicators and latency tracking.

---

## Quick Start (Local)

### 1. Prerequisites
- Python 3.10+
- Docker Desktop (for Postgres & Langfuse)

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/your-username/ragflow.git
cd ragflow

# Activate Virtual Environment
python -m venv venv
# On Windows: .\venv\Scripts\activate
# On Mac/Linux: source venv/bin/activate

# Install Dependencies
pip install -r requirements.txt
```

### 3. Environment Setup
Copy the `.env.example` file to `.env` and fill in your API keys:
```bash
cp .env.example .env
```

### 4. Running the Application
Start the background services (Database & Langfuse):
```bash
docker-compose up -d
```
Start the FastAPI server:
```bash
uvicorn backend.api:app --reload
```
Navigate to `http://localhost:8000` to interact with the RAGgent UI!

---

## Deployment
This repository is pre-configured for easy deployment on **Railway** and **Render**.

### Deploy to Railway
1. Connect your GitHub repository to Railway.
2. Railway will automatically detect the `railway.toml` file and build the project.
3. Add your environment variables (from `.env`) in the Railway dashboard.
4. Add a **Persistent Volume** mounted to `/app/data` to ensure your database and vector indices survive redeployments.

---

## Project Structure
* `backend/` - FastAPI server, LangChain agents, FAISS pipeline, and authentication.
* `frontend/` - Enterprise UI built with vanilla HTML/CSS/JS.
* `data/` - (Git Ignored) Stores SQLite DB and FAISS index files.
* `Documentation/` - Technical R&D specs and architectural overviews.

## License
Distributed under the MIT License. See `LICENSE` for more information.
