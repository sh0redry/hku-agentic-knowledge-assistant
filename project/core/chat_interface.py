import json
import re
from langchain_core.messages import HumanMessage, AIMessageChunk, ToolMessage


SILENT_NODES = {"rewrite_query"}
SYSTEM_NODES = {"summarize_history", "rewrite_query"}

SYSTEM_NODE_CONFIG = {
    "rewrite_query": {"title": "Thinking"},
    "summarize_history": {"title": "Context"},
}


def make_message(content, *, title=None, node=None):
    msg = {"role": "assistant", "content": content}
    if title or node:
        msg["metadata"] = {k: v for k, v in {"title": title, "node": node}.items() if v}
    return msg


def find_msg_idx(messages, node):
    return next(
        (i for i, m in enumerate(messages) if m.get("metadata", {}).get("node") == node),
        None,
    )


def parse_rewrite_json(buffer):
    match = re.search(r"\{.*\}", buffer, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except Exception:
        return None


def format_rewrite_content(buffer):
    data = parse_rewrite_json(buffer)
    if not data:
        return "Analyzing the question..."
    if data.get("is_clear"):
        lines = ["**Query is clear**"]
        if data.get("questions"):
            lines += ["\n**Rewritten queries:**"] + [f"- {q}" for q in data["questions"]]
    else:
        lines = ["**Query is unclear**"]
        clarification = data.get("clarification_needed", "")
        if clarification and clarification.strip().lower() != "no":
            lines.append(f"\nClarification needed: *{clarification}*")
    return "\n".join(lines)


def final_visible_messages(messages):
    """Hide transient thinking/tool messages after streaming completes."""
    visible = []
    for msg in messages:
        metadata = msg.get("metadata", {})
        node = metadata.get("node")
        if node in SYSTEM_NODES or node == "tool":
            continue
        if metadata.get("title", "").startswith("Tool:"):
            continue
        visible.append(msg)
    return visible


class ChatInterface:
    def __init__(self, rag_system):
        self.rag_system = rag_system

    def _handle_system_node(self, chunk, node, response_messages, system_node_buffer):
        system_node_buffer[node] = system_node_buffer.get(node, "") + chunk.content
        buffer = system_node_buffer[node]
        title = SYSTEM_NODE_CONFIG[node]["title"]
        content = format_rewrite_content(buffer) if node == "rewrite_query" else buffer

        idx = find_msg_idx(response_messages, node)
        if idx is None:
            response_messages.append(make_message(content, title=title, node=node))
        else:
            response_messages[idx]["content"] = content

        if node == "rewrite_query":
            self._surface_clarification(buffer, response_messages)

    def _surface_clarification(self, buffer, response_messages):
        data = parse_rewrite_json(buffer) or {}
        clarification = data.get("clarification_needed", "")
        if not data.get("is_clear") and clarification.strip().lower() not in ("", "no"):
            cidx = find_msg_idx(response_messages, "clarification")
            if cidx is None:
                response_messages.append(make_message(clarification, node="clarification"))
            else:
                response_messages[cidx]["content"] = clarification

    def _handle_tool_call(self, chunk, response_messages, active_tool_calls):
        for tc in chunk.tool_calls:
            if tc.get("id") and tc["id"] not in active_tool_calls:
                response_messages.append(
                    make_message(f"Running `{tc['name']}`...", title=f"Tool: {tc['name']}", node="tool")
                )
                active_tool_calls[tc["id"]] = len(response_messages) - 1

    def _handle_tool_result(self, chunk, response_messages, active_tool_calls):
        idx = active_tool_calls.get(chunk.tool_call_id)
        if idx is not None:
            preview = str(chunk.content)[:300]
            suffix = "\n..." if len(str(chunk.content)) > 300 else ""
            response_messages[idx]["content"] = f"```\n{preview}{suffix}\n```"

    def _handle_llm_token(self, chunk, response_messages):
        last = response_messages[-1] if response_messages else None
        if not (last and last.get("role") == "assistant" and "metadata" not in last):
            response_messages.append(make_message(""))
        response_messages[-1]["content"] += chunk.content

    def chat(self, message, history):
        if not self.rag_system.agent_graph:
            yield "System not initialized."
            return

        config = self.rag_system.get_config()
        current_state = self.rag_system.agent_graph.get_state(config)

        try:
            if current_state.next:
                self.rag_system.agent_graph.update_state(
                    config, {"messages": [HumanMessage(content=message.strip())]}
                )
                stream_input = None
            else:
                stream_input = {"messages": [HumanMessage(content=message.strip())]}

            response_messages = []
            active_tool_calls = {}
            system_node_buffer = {}

            for chunk, metadata in self.rag_system.agent_graph.stream(stream_input, config=config, stream_mode="messages"):
                node = metadata.get("langgraph_node", "")

                if node in SYSTEM_NODES and isinstance(chunk, AIMessageChunk) and chunk.content:
                    self._handle_system_node(chunk, node, response_messages, system_node_buffer)

                elif hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    self._handle_tool_call(chunk, response_messages, active_tool_calls)

                elif isinstance(chunk, ToolMessage):
                    self._handle_tool_result(chunk, response_messages, active_tool_calls)

                elif isinstance(chunk, AIMessageChunk) and chunk.content and node not in SILENT_NODES:
                    self._handle_llm_token(chunk, response_messages)

                yield response_messages

            yield final_visible_messages(response_messages)

        except Exception as e:
            yield f"Error: {str(e)}"

    def clear_session(self):
        self.rag_system.reset_thread()
        self.rag_system.observability.flush()
