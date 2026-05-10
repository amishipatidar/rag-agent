"""
LangGraph Orchestrator & Agents
- AgentState schema
- Intent Classifier Node
- Specialist Agents: Summary, Suggestion, Modification
- Assembled state graph
"""
from typing import TypedDict, List, Optional, Literal
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


# ── Agent State ───────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """State object passed through the LangGraph nodes."""
    user_message: str
    retrieved_chunks: List[str]
    conversation_history: List[dict]
    provider: str
    model: str
    intent: Optional[str]
    response: Optional[str]


# ── System Prompts ────────────────────────────────────────────────────────

CLASSIFIER_PROMPT = """You are an intent classifier for a document-based AI assistant.
Given the user's message, classify the intent into exactly one of these categories:
- "summary": The user wants a summary, overview, or explanation of the document content.
- "suggestion": The user wants suggestions, recommendations, or improvements based on the document.
- "modification": The user wants to modify, edit, rewrite, or change the document content.

Respond with ONLY one word: summary, suggestion, or modification."""

SUMMARY_PROMPT = """You are a document summarization specialist. Your job is to provide clear,
concise, and accurate summaries based on the retrieved document context.
Always base your answers on the provided context. If the context doesn't contain
relevant information, say so honestly."""

SUGGESTION_PROMPT = """You are a document improvement specialist. Your job is to analyze
the retrieved document context and provide actionable suggestions, recommendations,
and improvements. Be specific and constructive in your feedback."""

MODIFICATION_PROMPT = """You are a document editing specialist. Your job is to help users
modify, rewrite, or restructure document content based on their request.
Provide the modified content directly, maintaining the document's style and tone
while incorporating the requested changes."""


# ── Intent Classifier ─────────────────────────────────────────────────────

def classify_intent(state: AgentState, llm) -> AgentState:
    """
    Classify the user's intent into summary, suggestion, or modification.

    Args:
        state: The current agent state.
        llm: A LangChain chat model instance.

    Returns:
        Updated state with the 'intent' field set.
    """
    messages = [
        SystemMessage(content=CLASSIFIER_PROMPT),
        HumanMessage(content=state["user_message"])
    ]

    response = llm.invoke(messages)
    intent_text = response.content.strip().lower()

    # Parse the intent - be lenient with LLM output
    if "summary" in intent_text:
        intent = "summary"
    elif "suggestion" in intent_text:
        intent = "suggestion"
    elif "modification" in intent_text:
        intent = "modification"
    else:
        intent = "summary"  # Default fallback

    return {**state, "intent": intent}


# ── Specialist Agent Runner ───────────────────────────────────────────────

def run_agent(state: AgentState, llm, system_prompt: str) -> AgentState:
    """
    Run a specialist agent with the given system prompt.

    Args:
        state: The current agent state.
        llm: A LangChain chat model instance.
        system_prompt: The system prompt for this specialist.

    Returns:
        Updated state with the 'response' field set.
    """
    messages = [SystemMessage(content=system_prompt)]

    # Add conversation history
    for msg in state.get("conversation_history", []):
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    # Add retrieved context
    chunks = state.get("retrieved_chunks", [])
    if chunks:
        context = "\n\n---\n\n".join(chunks)
        messages.append(HumanMessage(content=f"[Document Context]\n{context}"))

    # Add the current user message
    messages.append(HumanMessage(content=state["user_message"]))

    response = llm.invoke(messages)
    return {**state, "response": response.content}


def get_agent_messages(state: AgentState, system_prompt: str) -> list:
    """
    Build the message list for a specialist agent without invoking the LLM.
    Used by the streaming endpoint to construct messages before calling llm.stream().

    Args:
        state: The current agent state (with intent already classified).
        system_prompt: The system prompt for the specialist.

    Returns:
        A list of LangChain message objects ready to be passed to llm.stream().
    """
    messages = [SystemMessage(content=system_prompt)]

    for msg in state.get("conversation_history", []):
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    chunks = state.get("retrieved_chunks", [])
    if chunks:
        context = "\n\n---\n\n".join(chunks)
        messages.append(HumanMessage(content=f"[Document Context]\n{context}"))

    messages.append(HumanMessage(content=state["user_message"]))
    return messages


def run_summary_agent(state: AgentState, llm) -> AgentState:
    """Run the Summary specialist agent."""
    return run_agent(state, llm, SUMMARY_PROMPT)


def run_suggestion_agent(state: AgentState, llm) -> AgentState:
    """Run the Suggestion specialist agent."""
    return run_agent(state, llm, SUGGESTION_PROMPT)


def run_modification_agent(state: AgentState, llm) -> AgentState:
    """Run the Modification specialist agent."""
    return run_agent(state, llm, MODIFICATION_PROMPT)


# ── Graph Assembly ────────────────────────────────────────────────────────

def build_graph(llm):
    """
    Build and compile the LangGraph state graph.

    Args:
        llm: A LangChain chat model instance.

    Returns:
        A compiled LangGraph that can be invoked with an AgentState.
    """
    from langgraph.graph import StateGraph, END

    def classify_node(state: AgentState) -> AgentState:
        return classify_intent(state, llm)

    def summary_node(state: AgentState) -> AgentState:
        return run_summary_agent(state, llm)

    def suggestion_node(state: AgentState) -> AgentState:
        return run_suggestion_agent(state, llm)

    def modification_node(state: AgentState) -> AgentState:
        return run_modification_agent(state, llm)

    def route_by_intent(state: AgentState) -> str:
        return state.get("intent", "summary")

    # Build the graph
    graph = StateGraph(AgentState)

    graph.add_node("classify", classify_node)
    graph.add_node("summary", summary_node)
    graph.add_node("suggestion", suggestion_node)
    graph.add_node("modification", modification_node)

    graph.set_entry_point("classify")

    graph.add_conditional_edges(
        "classify",
        route_by_intent,
        {
            "summary": "summary",
            "suggestion": "suggestion",
            "modification": "modification",
        }
    )

    graph.add_edge("summary", END)
    graph.add_edge("suggestion", END)
    graph.add_edge("modification", END)

    return graph.compile()
