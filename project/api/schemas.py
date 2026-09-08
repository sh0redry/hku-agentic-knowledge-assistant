from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class IntegrationError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    recovery: str | None = Field(default=None, max_length=1000)
    details: list[dict[str, Any]] | None = None


class IntegrationTaskSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    capability: str
    status: str
    phase: str
    correlation_id: str
    error: dict[str, Any] | None = None


class IntegrationResponse(BaseModel):
    """Stable host-facing response envelope for GUI and agent adapters."""

    model_config = ConfigDict(extra="forbid")

    api_version: Literal["v1"] = "v1"
    ok: bool
    read_only: Literal[True] = True
    correlation_id: str = Field(min_length=1, max_length=128)
    result: dict[str, Any] | None = None
    task: IntegrationTaskSummary | None = None
    error: IntegrationError | None = None
