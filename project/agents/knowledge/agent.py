from __future__ import annotations

import asyncio
import threading
from typing import Any

from pydantic import BaseModel, Field

from agents.base import BaseCapability
from agents.models import (
    CapabilityManifest,
    CapabilityMode,
    ConfirmationMode,
    ExecutionContext,
    RiskLevel,
)


class KnowledgeAnswerRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[dict[str, Any]] = Field(default_factory=list)


class KnowledgeAnswerCapability(BaseCapability):
    input_model = KnowledgeAnswerRequest
    manifest = CapabilityManifest(
        id="knowledge.answer",
        agent="knowledge",
        title="HKU Knowledge Answer",
        description="Answer an HKU question using the existing knowledge assistant.",
        mode=CapabilityMode.READ,
        risk=RiskLevel.LOW,
        confirmation=ConfirmationMode.NONE,
        input_schema="KnowledgeAnswerRequest",
        output_schema="KnowledgeAnswerResult",
        timeout_seconds=300,
    )

    def __init__(self):
        self._chat = None
        self._initialization_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._initialization_status = "not_started"
        self._initialization_error = None
        self._initialization_progress = 0.0
        self._initialization_description = "Not initialized"

    @property
    def initialization_status(self) -> str:
        with self._state_lock:
            return self._initialization_status

    @property
    def initialization_error(self) -> str | None:
        with self._state_lock:
            return self._initialization_error

    def initialization_snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "status": self._initialization_status,
                "error": self._initialization_error,
                "progress": self._initialization_progress,
                "description": self._initialization_description,
            }

    def _set_initialization_state(
        self,
        *,
        status: str | None = None,
        error: str | None = None,
        progress: float | None = None,
        description: str | None = None,
    ) -> None:
        with self._state_lock:
            if status is not None:
                self._initialization_status = status
            self._initialization_error = error
            if progress is not None:
                self._initialization_progress = max(0.0, min(1.0, progress))
            if description is not None:
                self._initialization_description = description

    def start_initialize(self) -> dict[str, Any]:
        with self._state_lock:
            if self._initialization_status in {"initializing", "ready"}:
                return {
                    "status": self._initialization_status,
                    "error": self._initialization_error,
                    "progress": self._initialization_progress,
                    "description": self._initialization_description,
                }
            self._initialization_status = "initializing"
            self._initialization_error = None
            self._initialization_progress = 0.01
            self._initialization_description = "Starting the knowledge initializer"

        threading.Thread(target=self._initialize_in_background, daemon=True).start()
        return self.initialization_snapshot()

    def _initialize_in_background(self) -> None:
        try:
            self.initialize()
        except Exception:
            # The error and retryable state are exposed through the snapshot.
            pass

    def persisted_input(self, validated_input: KnowledgeAnswerRequest) -> dict[str, Any]:
        return {
            "message": "[REDACTED]",
            "message_length": len(validated_input.message),
            "history_items": len(validated_input.history),
        }

    def persisted_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "answer": "[REDACTED]",
            "answer_length": len(result.get("answer", "")),
            "message_count": len(result.get("messages", [])),
        }

    def initialize(self, progress_callback=None):
        def report(value, description):
            self._set_initialization_state(
                status="ready" if value >= 1.0 else "initializing",
                error=None,
                progress=value,
                description=description,
            )
            if progress_callback:
                progress_callback(value, description)

        if self._chat is None:
            report(0.01, "Waiting for the knowledge initializer")
            with self._initialization_lock:
                if self._chat is None:
                    self._set_initialization_state(
                        status="initializing", error=None, progress=0.01
                    )
                    rag_system = None
                    try:
                        from core.chat_interface import ChatInterface
                        from core.rag_system import RAGSystem

                        rag_system = RAGSystem()
                        rag_system.initialize(progress_callback=report)
                        self._chat = ChatInterface(rag_system)
                    except Exception as exc:
                        if rag_system is not None:
                            try:
                                rag_system.close()
                            except Exception:
                                pass
                        self._set_initialization_state(
                            status="failed",
                            error=str(exc),
                            description="Knowledge Agent initialization failed",
                        )
                        raise
        report(1.0, "Knowledge agent is ready")
        return self._chat

    def _get_chat(self):
        return self.initialize()

    def _answer(self, request: KnowledgeAnswerRequest, session_id: str) -> dict:
        chat = self._get_chat()
        final = None
        for chunk in chat.chat(request.message, request.history, thread_id=session_id):
            final = chunk
        if isinstance(final, str):
            messages = [{"role": "assistant", "content": final}]
        else:
            messages = final or []
        answer = "\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "assistant" and message.get("content")
        ).strip()
        return {"answer": answer, "messages": messages}

    async def execute(self, validated_input: KnowledgeAnswerRequest, context: ExecutionContext) -> dict:
        return await asyncio.to_thread(self._answer, validated_input, context.session_id)
