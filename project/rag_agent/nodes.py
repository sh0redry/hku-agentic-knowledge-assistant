from typing import Literal, Set
from langchain_core.messages import SystemMessage, HumanMessage, RemoveMessage, AIMessage, ToolMessage
from langgraph.types import Command
from .graph_state import State, AgentState
from .schemas import QueryAnalysis
from .prompts import *
from utils import estimate_context_tokens
from core.cache import answer_cache, cache_key, rewrite_cache
import config
from config import BASE_TOKEN_THRESHOLD, TOKEN_GROWTH_FACTOR

def summarize_history(state: State, llm, fallback_llm=None):
    if len(state["messages"]) < 4:
        return {"conversation_summary": ""}
    
    relevant_msgs = [
        msg for msg in state["messages"][:-1]
        if isinstance(msg, (HumanMessage, AIMessage)) and not getattr(msg, "tool_calls", None)
    ]

    if not relevant_msgs:
        return {"conversation_summary": ""}
    
    conversation = "Conversation history:\n"
    for msg in relevant_msgs[-6:]:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        conversation += f"{role}: {msg.content}\n"

    try:
        summary_response = llm.with_config(temperature=0.2).invoke([SystemMessage(content=get_conversation_summary_prompt()), HumanMessage(content=conversation)])
    except Exception:
        if fallback_llm is None or fallback_llm is llm:
            raise
        summary_response = fallback_llm.with_config(temperature=0.2).invoke([SystemMessage(content=get_conversation_summary_prompt()), HumanMessage(content=conversation)])
    return {"conversation_summary": summary_response.content, "agent_answers": [{"__reset__": True}]}

def rewrite_query(state: State, llm, fallback_llm=None):
    last_message = state["messages"][-1]
    conversation_summary = state.get("conversation_summary", "")

    context_section = (f"Conversation Context:\n{conversation_summary}\n" if conversation_summary.strip() else "") + f"User Query:\n{last_message.content}\n"
    cached = rewrite_cache.get(cache_key(conversation_summary, last_message.content))
    if cached:
        if cached["is_clear"]:
            delete_all = [RemoveMessage(id=m.id) for m in state["messages"] if not isinstance(m, SystemMessage)]
            return {
                "questionIsClear": True,
                "messages": delete_all,
                "originalQuery": last_message.content,
                "rewrittenQuestions": cached["questions"],
            }
        return {"questionIsClear": False, "messages": [AIMessage(content=cached["clarification_needed"])]}

    try:
        llm_with_structure = llm.with_config(temperature=0.1).with_structured_output(QueryAnalysis)
        response = llm_with_structure.invoke([SystemMessage(content=get_rewrite_query_prompt()), HumanMessage(content=context_section)])
    except Exception:
        if fallback_llm is None or fallback_llm is llm:
            raise
        llm_with_structure = fallback_llm.with_config(temperature=0.1).with_structured_output(QueryAnalysis)
        response = llm_with_structure.invoke([SystemMessage(content=get_rewrite_query_prompt()), HumanMessage(content=context_section)])

    if response.questions and response.is_clear:
        rewrite_cache.set(
            cache_key(conversation_summary, last_message.content),
            {"is_clear": True, "questions": response.questions, "clarification_needed": ""},
        )
        delete_all = [RemoveMessage(id=m.id) for m in state["messages"] if not isinstance(m, SystemMessage)]
        return {"questionIsClear": True, "messages": delete_all, "originalQuery": last_message.content, "rewrittenQuestions": response.questions}

    clarification = response.clarification_needed if response.clarification_needed and len(response.clarification_needed.strip()) > 10 else "I need more information to understand your question."
    rewrite_cache.set(
        cache_key(conversation_summary, last_message.content),
        {"is_clear": False, "questions": [], "clarification_needed": clarification},
    )
    return {"questionIsClear": False, "messages": [AIMessage(content=clarification)]}

def request_clarification(state: State):
    return {}

def direct_answer(state: State, llm, collection):
    question = state["rewrittenQuestions"][0]
    original_query = state.get("originalQuery", question)
    queries = [question]
    if original_query and original_query not in queries:
        queries.append(original_query)
    if "简历" in question and "候选人姓名" in question:
        queries.append("姓名 候选人 简历 name candidate")

    max_attempts = max(1, config.DIRECT_RETRIEVAL_RETRIES)
    docs = []
    for query in queries[:max_attempts]:
        docs = collection.similarity_search(
            query,
            k=config.DIRECT_RETRIEVAL_LIMIT,
            score_threshold=config.SEARCH_SCORE_THRESHOLD,
        )
        if docs:
            break

    if not docs:
        msg = "I couldn't find any information to answer your question in the available sources."
        return {"direct_answer": msg, "messages": [AIMessage(content=msg)]}

    context = "\n\n".join(
        f"Source: {doc.metadata.get('source', 'unknown')}\n"
        f"Source URL: {doc.metadata.get('source_url', '')}\n"
        f"Title: {doc.metadata.get('title', '')}\n"
        f"Content:\n{doc.page_content.strip()}"
        for doc in docs
    )
    sources = sorted({
        doc.metadata.get("source_url") or doc.metadata.get("source", "")
        for doc in docs
        if doc.metadata.get("source_url") or doc.metadata.get("source")
    })
    answer_key = cache_key(question, context)
    cached = answer_cache.get(answer_key)
    if cached:
        return {"direct_answer": cached, "messages": [AIMessage(content=cached)]}

    prompt = (
        f"User question:\n{original_query}\n\n"
        f"Rewritten question:\n{question}\n\n"
        f"Retrieved context:\n{context}\n\n"
        f"Allowed sources:\n" + "\n".join(f"- {source}" for source in sources)
    )
    response = llm.invoke([SystemMessage(content=get_direct_answer_prompt()), HumanMessage(content=prompt)])
    answer_cache.set(answer_key, response.content)
    return {"direct_answer": response.content, "messages": [AIMessage(content=response.content)]}

# --- Agent Nodes ---
def orchestrator(state: AgentState, llm_with_tools):
    context_summary = state.get("context_summary", "").strip()
    sys_msg = SystemMessage(content=get_orchestrator_prompt())
    summary_injection = (
        [HumanMessage(content=f"[COMPRESSED CONTEXT FROM PRIOR RESEARCH]\n\n{context_summary}")]
        if context_summary else []
    )
    if not state.get("messages"):
        human_msg = HumanMessage(content=state["question"])
        force_search = HumanMessage(content="YOU MUST CALL 'search_child_chunks' AS THE FIRST STEP TO ANSWER THIS QUESTION.")
        response = llm_with_tools.invoke([sys_msg] + summary_injection + [human_msg, force_search])
        return {"messages": [human_msg, response], "tool_call_count": len(response.tool_calls or []), "iteration_count": 1}

    response = llm_with_tools.invoke([sys_msg] + summary_injection + state["messages"])
    tool_calls = response.tool_calls if hasattr(response, "tool_calls") else []
    return {"messages": [response], "tool_call_count": len(tool_calls) if tool_calls else 0, "iteration_count": 1}

def fallback_response(state: AgentState, llm):
    seen = set()
    unique_contents = []
    for m in state["messages"]:
        if isinstance(m, ToolMessage) and m.content not in seen:
            unique_contents.append(m.content)
            seen.add(m.content)

    context_summary = state.get("context_summary", "").strip()

    context_parts = []
    if context_summary:
        context_parts.append(f"## Compressed Research Context (from prior iterations)\n\n{context_summary}")
    if unique_contents:
        context_parts.append(
            "## Retrieved Data (current iteration)\n\n" +
            "\n\n".join(f"--- DATA SOURCE {i} ---\n{content}" for i, content in enumerate(unique_contents, 1))
        )

    context_text = "\n\n".join(context_parts) if context_parts else "No data was retrieved from the documents."

    prompt_content = (
        f"USER QUERY: {state.get('question')}\n\n"
        f"{context_text}\n\n"
        f"INSTRUCTION:\nProvide the best possible answer using only the data above."
    )
    response = llm.invoke([SystemMessage(content=get_fallback_response_prompt()), HumanMessage(content=prompt_content)])
    return {"messages": [response]}

def should_compress_context(state: AgentState) -> Command[Literal["compress_context", "orchestrator"]]:
    messages = state["messages"]

    new_ids: Set[str] = set()
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc["name"] == "retrieve_parent_chunks":
                    raw = tc["args"].get("parent_id") or tc["args"].get("id") or tc["args"].get("ids") or []
                    if isinstance(raw, str):
                        new_ids.add(f"parent::{raw}")
                    else:
                        new_ids.update(f"parent::{r}" for r in raw)

                elif tc["name"] == "search_child_chunks":
                    query = tc["args"].get("query", "")
                    if query:
                        new_ids.add(f"search::{query}")
            break

    updated_ids = state.get("retrieval_keys", set()) | new_ids

    current_token_messages = estimate_context_tokens(messages)
    current_token_summary = estimate_context_tokens([HumanMessage(content=state.get("context_summary", ""))])
    current_tokens = current_token_messages + current_token_summary

    max_allowed = BASE_TOKEN_THRESHOLD + int(current_token_summary * TOKEN_GROWTH_FACTOR)

    goto = "compress_context" if current_tokens > max_allowed else "orchestrator"
    return Command(update={"retrieval_keys": updated_ids}, goto=goto)

def compress_context(state: AgentState, llm):
    messages = state["messages"]
    existing_summary = state.get("context_summary", "").strip()

    if not messages:
        return {}

    conversation_text = f"USER QUESTION:\n{state.get('question')}\n\nConversation to compress:\n\n"
    if existing_summary:
        conversation_text += f"[PRIOR COMPRESSED CONTEXT]\n{existing_summary}\n\n"

    for msg in messages[1:]:
        if isinstance(msg, AIMessage):
            tool_calls_info = ""
            if getattr(msg, "tool_calls", None):
                calls = ", ".join(f"{tc['name']}({tc['args']})" for tc in msg.tool_calls)
                tool_calls_info = f" | Tool calls: {calls}"
            conversation_text += f"[ASSISTANT{tool_calls_info}]\n{msg.content or '(tool call only)'}\n\n"
        elif isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", "tool")
            conversation_text += f"[TOOL RESULT — {tool_name}]\n{msg.content}\n\n"

    summary_response = llm.invoke([SystemMessage(content=get_context_compression_prompt()), HumanMessage(content=conversation_text)])
    new_summary = summary_response.content

    retrieved_ids: Set[str] = state.get("retrieval_keys", set())
    if retrieved_ids:
        parent_ids = sorted(r for r in retrieved_ids if r.startswith("parent::"))
        search_queries = sorted(r.replace("search::", "") for r in retrieved_ids if r.startswith("search::"))

        block = "\n\n---\n**Already executed (do NOT repeat):**\n"
        if parent_ids:
            block += "Parent chunks retrieved:\n" + "\n".join(f"- {p.replace('parent::', '')}" for p in parent_ids) + "\n"
        if search_queries:
            block += "Search queries already run:\n" + "\n".join(f"- {q}" for q in search_queries) + "\n"
        new_summary += block

    return {"context_summary": new_summary, "messages": [RemoveMessage(id=m.id) for m in messages[1:]]}

def collect_answer(state: AgentState):
    last_message = state["messages"][-1]
    is_valid = isinstance(last_message, AIMessage) and last_message.content and not last_message.tool_calls
    answer = last_message.content if is_valid else "Unable to generate an answer."
    return {
        "final_answer": answer,
        "agent_answers": [{"index": state["question_index"], "question": state["question"], "answer": answer}]
    }
# --- End of Agent Nodes---

def aggregate_answers(state: State, llm):
    if not state.get("agent_answers"):
        return {"messages": [AIMessage(content="No answers were generated.")]}

    sorted_answers = sorted(state["agent_answers"], key=lambda x: x["index"])

    formatted_answers = ""
    for i, ans in enumerate(sorted_answers, start=1):
        formatted_answers += (f"\nAnswer {i}:\n"f"{ans['answer']}\n")

    user_message = HumanMessage(content=f"""Original user question: {state["originalQuery"]}\nRetrieved answers:{formatted_answers}""")
    synthesis_response = llm.invoke([SystemMessage(content=get_aggregation_prompt()), user_message])
    return {"messages": [AIMessage(content=synthesis_response.content)]}
