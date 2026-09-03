from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from connectors.sis.models import CourseSelection


class StrictMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrowserTabState(StrictMessage):
    bound: bool = False
    origin: Literal["https://sis-main.hku.hk"] | None = None
    logged_in: bool | None = None
    page_kind: Literal["login", "home", "cart", "status", "blocked", "unknown"] = (
        "unknown"
    )
    term_label: str | None = Field(default=None, max_length=100)
    course_count: int = Field(default=0, ge=0, le=200)


class SISPageSnapshot(BrowserTabState):
    visible_courses: list[CourseSelection] = Field(default_factory=list, max_length=200)


class PairMessage(StrictMessage):
    type: Literal["pair"]
    token: str = Field(min_length=20, max_length=200)
    extension_version: str = Field(min_length=1, max_length=40)


class HeartbeatMessage(StrictMessage):
    type: Literal["heartbeat"]
    tab: BrowserTabState | None = None


class ExtensionResultMessage(StrictMessage):
    protocol_version: Literal[1]
    request_id: str = Field(min_length=1, max_length=100)
    ok: bool
    data: dict = Field(default_factory=dict)
    error: dict | None = None

    @field_validator("error")
    @classmethod
    def validate_error_shape(cls, value):
        if value is None:
            return value
        allowed = {"code", "message"}
        if set(value) - allowed:
            raise ValueError("Browser errors may only contain code and message.")
        return value

