from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from agents.errors import CapabilityError
from agents.models import utc_now


class LibraryBookingPreviewRegistry:
    """Process-local, short-lived attestations for supervised Library writes."""

    def __init__(self) -> None:
        self._previews: dict[str, dict] = {}
        self._consumed_by: dict[str, str] = {}

    def issue(self, digest: str, preview: dict) -> None:
        self._previews[digest] = deepcopy(preview)

    def require(self, digest: str) -> dict:
        preview = self._previews.get(digest)
        if preview is None:
            raise CapabilityError(
                "LIBRARY_BOOKING_PREVIEW_NOT_ISSUED",
                "The booking preview was not issued by this running HKU AGENTS process.",
            )
        expires_at = datetime.fromisoformat(str(preview["expires_at"]).replace("Z", "+00:00"))
        if expires_at <= utc_now():
            self._previews.pop(digest, None)
            raise CapabilityError(
                "LIBRARY_BOOKING_PREVIEW_EXPIRED",
                "The booking preview expired; refresh availability and create a new preview.",
            )
        if digest in self._consumed_by:
            raise CapabilityError(
                "LIBRARY_BOOKING_PREVIEW_ALREADY_USED",
                "The booking preview has already been consumed by another execution.",
                {"task_id": self._consumed_by[digest]},
            )
        return deepcopy(preview)

    def consume(self, digest: str, task_id: str) -> dict:
        preview = self.require(digest)
        self._consumed_by[digest] = task_id
        return preview

