from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CapabilityMode(str, Enum):
    READ = "read"
    WRITE = "write"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConfirmationMode(str, Enum):
    NONE = "none"
    EXPLICIT = "explicit"
    EXPLICIT_TWO_PHASE = "explicit_two_phase"


class TaskStatus(str, Enum):
    DRAFT = "draft"
    VALIDATING = "validating"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.UNKNOWN,
    TaskStatus.CANCELLED,
}


class CapabilityManifest(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: int = Field(default=1, ge=1)
    agent: str
    title: str
    description: str
    mode: CapabilityMode
    risk: RiskLevel
    confirmation: ConfirmationMode = ConfirmationMode.NONE
    required_connections: list[str] = Field(default_factory=list)
    availability: str = "available"
    input_schema: str
    output_schema: str
    timeout_seconds: int = Field(default=60, ge=1, le=3600)


class ExecutionContext(BaseModel):
    task_id: str
    session_id: str = "local-user"
    correlation_id: str


class TaskRecord(BaseModel):
    id: str
    capability: str
    status: TaskStatus
    phase: str
    input: dict[str, Any]
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    cancel_requested: bool = False
    correlation_id: str
    created_at: datetime
    updated_at: datetime


class TaskEvent(BaseModel):
    sequence: int
    task_id: str
    event_type: str
    data: dict[str, Any]
    created_at: datetime


class ActionDraft(BaseModel):
    id: str
    capability: str
    status: TaskStatus
    input: dict[str, Any]
    preview: dict[str, Any]
    preview_digest: str
    confirmation_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AuditEvent(BaseModel):
    id: int
    task_id: str | None = None
    capability: str
    event_type: str
    data: dict[str, Any]
    created_at: datetime
