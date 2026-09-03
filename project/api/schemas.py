from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[dict[str, Any]] = Field(default_factory=list)
    session_id: str = Field(default="local-user", min_length=1, max_length=128)


class ActionDraftRequest(BaseModel):
    capability: str
    input: dict[str, Any]


class ActionConfirmRequest(BaseModel):
    preview_digest: str = Field(min_length=64, max_length=64)


class ActionExecuteRequest(BaseModel):
    confirmation_token: str | None = None
    session_id: str = Field(default="local-user", min_length=1, max_length=128)
    correlation_id: str | None = None
