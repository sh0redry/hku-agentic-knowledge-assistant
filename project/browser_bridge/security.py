from __future__ import annotations

import re
from urllib.parse import urlsplit


_URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
_SECRET_PARAMETER_PATTERN = re.compile(
    r"(?i)\b(ticket|token|scope|relaystate|session|auth(?:orization)?)=([^\s&]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")


def sanitize_url(value: str) -> str:
    """Return an origin/path URL with credentials, query, and fragment removed."""

    try:
        parsed = urlsplit(value)
        port_number = parsed.port
    except ValueError:
        return "[REDACTED_URL]"
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "[REDACTED_URL]"
    port = f":{port_number}" if port_number is not None else ""
    origin = f"{parsed.scheme}://{parsed.hostname}{port}"
    path = parsed.path or "/"
    return f"{origin}{path[:300]}"


def sanitize_path(value: str) -> str:
    """Normalize a browser-reported path and reject any query or fragment."""

    if not value.startswith("/") or "?" in value or "#" in value:
        raise ValueError("Browser target path must exclude query strings and fragments.")
    return value[:300]


def redact_sensitive_text(value: object) -> str:
    """Remove authentication URL parameters before text reaches logs or API status."""

    text = str(value)
    text = _URL_PATTERN.sub(lambda match: sanitize_url(match.group(0)), text)
    text = _SECRET_PARAMETER_PATTERN.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", text
    )
    return _BEARER_PATTERN.sub(lambda match: f"{match.group(1)} [REDACTED]", text)
