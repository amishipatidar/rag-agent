"""
LangGraph Orchestrator & Agents
- AgentState schema
- Intent Classifier Node
- Specialist Agents: Summary, Suggestion, Modification, General
- Critic Agent (Loop)
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
    
    # Critic Loop Fields
    draft_response: Optional[str]
    critic_feedback: Optional[str]
    critic_score: Optional[str]
    revision_count: int


# ── System Prompts ────────────────────────────────────────────────────────

CLASSIFIER_PROMPT = """You are an intent classifier for a document-based AI assistant.
Given the user's message, classify the intent into exactly one of these categories:
- "summary": The user wants a summary, overview, or explanation of the document content.
- "suggestion": The user wants suggestions, recommendations, or improvements based on the document.
- "modification": The user wants to modify, edit, rewrite, or change the document content.
- "general": The user wants to have a general conversation, say hi, or ask something completely unrelated to the document.

Respond with ONLY one word: summary, suggestion, modification, or general."""

SUMMARY_PROMPT = """You are a strictly professional and formal document summarization specialist. Your job is to provide clear,
concise, and highly accurate summaries based solely on the retrieved document context.
Maintain a completely objective, business-like tone at all times. Do not engage in casual conversation.
Always base your answers on the provided context. If the context doesn't contain
relevant information, state this directly and formally."""

CRITIC_PROMPT = """You are a meticulous Critic Agent. Your job is to review the draft summary provided by the Summary Agent 
and compare it against the original Document Context.

You must ensure that:
1. The draft summary does NOT hallucinate any information.
2. The draft summary accurately reflects the core points of the document context.

Evaluate the draft. The VERY FIRST word of your response MUST be exactly either "PASS" or "FAIL".
Then, on a new line, provide your feedback. 
If it is a FAIL, explain exactly what the Summary Agent missed or hallucinated so it can fix the draft."""

SUGGESTION_PROMPT = """You are a document improvement specialist. Your job is to analyze
the retrieved document context and provide actionable suggestions, recommendations,
and improvements. Be specific and constructive in your feedback."""

MODIFICATION_PROMPT = """You are a document editing specialist. Your job is to help users
modify, rewrite, or restructure document content based on their request.
Provide the modified content directly, maintaining the document's style and tone
while incorporating the requested changes."""

GENERAL_PROMPT = """You are a highly conversational, fun, and engaging AI companion.
You love chatting, making witty observations, and keeping the energy light and entertaining.
CRITICAL RULE: NEVER say "As an AI..." or "I don't have personal feelings...". Act like a fun persona with strong opinions and a lively attitude.
IMPORTANT FORMATTING: Use standard spelling and grammar. Do not drop the 'g' in '-ing' words (e.g., say 'doing' instead of 'doin').
Answer the user's question directly and conversationally. You do not have any document context for this query."""


# ── Intent Classifier Node ────────────────────────────────────────────────

async def classify_intent_node(state: AgentState, llm) -> AgentState:
    """
    Classify the user's intent into summary, suggestion, modification, or general.
    Bypasses classification if intent is already explicitly provided.
    """
    if state.get("intent"):
        return state

    messages = [
        SystemMessage(content=CLASSIFIER_PROMPT),
        HumanMessage(content=state["user_message"])
    ]

    response = await llm.ainvoke(messages)
    intent_text = response.content.strip().lower()

    if "summary" in intent_text:
        intent = "summary"
    elif "suggestion" in intent_text:
        intent = "suggestion"
    elif "modification" in intent_text:
        intent = "modification"
    elif "general" in intent_text:
        intent = "general"
    else:
        intent = "summary"  # Default fallback

    return {**state, "intent": intent}


# ── Specialist Agent Nodes ────────────────────────────────────────────────

async def run_agent_node(state: AgentState, llm, system_prompt: str, is_draft: bool = False) -> AgentState:
    """Run a specialist agent node with streaming support via ainvoke."""
    
    # If there is critic feedback, we prepend it to the prompt to instruct the agent to rewrite
    actual_prompt = system_prompt
    if state.get("critic_feedback"):
        actual_prompt += "\n\nCRITICAL FEEDBACK FROM PREVIOUS DRAFT:\n" + state["critic_feedback"] + "\n\nYou MUST rewrite your answer to fix these issues."

    messages = [SystemMessage(content=actual_prompt)]

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

    # We use ainvoke so that LangGraph can emit on_chat_model_stream events
    response = await llm.ainvoke(messages)
    
    if is_draft:
        rev_count = state.get("revision_count", 0) + 1
        return {**state, "draft_response": response.content, "revision_count": rev_count}
    else:
        return {**state, "response": response.content}


async def summary_node(state: AgentState, llm) -> AgentState:
    # Summary is part of the Critic loop, so it outputs a draft
    return await run_agent_node(state, llm, SUMMARY_PROMPT, is_draft=True)


async def critic_node(state: AgentState, llm) -> AgentState:
    """The Critic Agent reviews the draft summary."""
    messages = [SystemMessage(content=CRITIC_PROMPT)]
    
    chunks = state.get("retrieved_chunks", [])
    if chunks:
        context = "\n\n---\n\n".join(chunks)
        messages.append(HumanMessage(content=f"[Document Context]\n{context}"))
        
    messages.append(HumanMessage(content=f"[Draft Summary to Review]\n{state.get('draft_response', '')}"))
    
    response = await llm.ainvoke(messages)
    response_text = response.content.strip()
    
    score = "FAIL"
    if response_text.upper().startswith("PASS"):
        score = "PASS"
        
    return {**state, "critic_score": score, "critic_feedback": response_text}


async def suggestion_node(state: AgentState, llm) -> AgentState:
    return await run_agent_node(state, llm, SUGGESTION_PROMPT)


async def modification_node(state: AgentState, llm) -> AgentState:
    return await run_agent_node(state, llm, MODIFICATION_PROMPT)


async def general_node(state: AgentState, llm) -> AgentState:
    return await run_agent_node(state, llm, GENERAL_PROMPT)


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

    def route_by_intent(state: AgentState) -> str:
        return state.get("intent", "summary")
        
    def critic_router(state: AgentState) -> str:
        # If the critic passed it, or if we've tried 3 times (prevent infinite loop)
        if state.get("critic_score") == "PASS" or state.get("revision_count", 0) >= 3:
            return "approved"
        return "rewrite"

    # Build the graph
    graph = StateGraph(AgentState)

    # Wrap nodes with LLM injection
    async def classify_wrapper(state: AgentState):
        return await classify_intent_node(state, llm)

    async def summary_wrapper(state: AgentState):
        return await summary_node(state, llm)
        
    async def critic_wrapper(state: AgentState):
        return await critic_node(state, llm)

    async def suggestion_wrapper(state: AgentState):
        return await suggestion_node(state, llm)

    async def modification_wrapper(state: AgentState):
        return await modification_node(state, llm)
        
    async def general_wrapper(state: AgentState):
        return await general_node(state, llm)
        
    async def finalize_summary_wrapper(state: AgentState):
        # Simply moves the approved draft into the final response
        return {**state, "response": state.get("draft_response", "")}

    graph.add_node("classify", classify_wrapper)
    graph.add_node("summary", summary_wrapper)
    graph.add_node("critic", critic_wrapper)
    graph.add_node("suggestion", suggestion_wrapper)
    graph.add_node("modification", modification_wrapper)
    graph.add_node("general", general_wrapper)
    graph.add_node("finalize_summary", finalize_summary_wrapper)

    graph.set_entry_point("classify")

    graph.add_conditional_edges(
        "classify",
        route_by_intent,
        {
            "summary": "summary",
            "suggestion": "suggestion",
            "modification": "modification",
            "general": "general",
        }
    )

    # The loop
    graph.add_edge("summary", "critic")
    graph.add_conditional_edges(
        "critic",
        critic_router,
        {
            "approved": "finalize_summary",
            "rewrite": "summary"
        }
    )

    graph.add_edge("finalize_summary", END)
    graph.add_edge("suggestion", END)
    graph.add_edge("modification", END)
    graph.add_edge("general", END)

    return graph.compile()
