from typing import Literal
from langgraph.types import Send
from .graph_state import State, AgentState
from config import DIRECT_SINGLE_QUESTION, MAX_ITERATIONS, MAX_TOOL_CALLS

def route_after_rewrite(state: State) -> Literal["request_clarification", "direct_answer", "agent"]:
    if not state.get("questionIsClear", False):
        return "request_clarification"
    elif DIRECT_SINGLE_QUESTION and len(state.get("rewrittenQuestions", [])) == 1:
        return "direct_answer"
    else:
        return [
                Send("agent", {"question": query, "question_index": idx, "messages": []})
                for idx, query in enumerate(state["rewrittenQuestions"])
            ]
    
def route_after_orchestrator_call(state: AgentState) -> Literal["tool", "fallback_response", "collect_answer"]:
    iteration = state.get("iteration_count", 0)
    tool_count = state.get("tool_call_count", 0)

    if iteration >= MAX_ITERATIONS or tool_count > MAX_TOOL_CALLS:
        return "fallback_response"

    last_message = state["messages"][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []

    if not tool_calls:
        return "collect_answer"
    
    return "tools"
