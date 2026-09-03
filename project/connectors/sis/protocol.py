from __future__ import annotations

import re
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


PROTOCOL_VERSION = 1
SIS_ORIGIN = "https://sis-main.hku.hk"
SENSITIVE_KEY_PATTERN = re.compile(
    r"password|passwd|pwd|cookie|authorization|access[_-]?token|refresh[_-]?token|secret",
    re.IGNORECASE,
)


class BrowserCommandName(str, Enum):
    HEALTH = "browser.health"
    BIND_SIS_TAB = "sis.bind_tab"
    INSPECT_PAGE = "sis.inspect_page"
    INSPECT_CART = "sis.inspect_cart"
    PREFLIGHT = "sis.preflight"
    GET_STATUS = "sis.get_status"


class BrowserCommand(BaseModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    command: BrowserCommandName
    payload: dict[str, Any] = Field(default_factory=dict)


class BrowserCommandResult(BaseModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    request_id: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


def sanitize_for_log(value: Any) -> Any:
    """Recursively redact known secret fields before local audit/log storage."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE_KEY_PATTERN.search(str(key)) else sanitize_for_log(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_for_log(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_log(item) for item in value]
    return value
