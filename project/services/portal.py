from __future__ import annotations

import threading
from datetime import datetime, timezone

from browser_bridge.models import PortalNotice


class PortalNoticeService:
    """Process-local cache for notices visible on the authenticated Portal home page."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot: dict | None = None

    def update(self, notices: list[dict], source: dict) -> dict:
        normalized = [
            PortalNotice.model_validate(item).model_dump(mode="json") for item in notices
        ]
        normalized.sort(
            key=lambda item: (item["published_date"], item["title"]), reverse=True
        )
        fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        snapshot = {
            "notices": normalized,
            "notice_count": len(normalized),
            "fetched_at": fetched_at,
            "source": source,
            "cache_scope": "process_memory_only",
        }
        with self._lock:
            self._snapshot = snapshot
        return dict(snapshot)

    def snapshot(self) -> dict | None:
        with self._lock:
            return dict(self._snapshot) if self._snapshot else None
