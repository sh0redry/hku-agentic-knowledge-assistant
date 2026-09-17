from __future__ import annotations

import threading
from datetime import datetime, timezone

from browser_bridge.models import MoodleAssignment, MoodleCourse


class MoodleCourseService:
    """Process-local cache for private Moodle course membership."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot: dict | None = None

    def update(self, courses: list[dict], source: dict) -> dict:
        normalized: list[dict] = []
        seen: set[str] = set()
        duplicates_removed = 0
        for item in courses:
            course = MoodleCourse.model_validate(item).model_dump(mode="json")
            if course["course_id"] in seen:
                duplicates_removed += 1
                continue
            seen.add(course["course_id"])
            normalized.append(course)
        fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        snapshot = {
            "courses": normalized,
            "course_count": len(normalized),
            "fetched_at": fetched_at,
            "source": source,
            "cache_scope": "process_memory_only",
            "normalization_warnings": (
                [f"Removed {duplicates_removed} duplicate Moodle course row(s)."]
                if duplicates_removed
                else []
            ),
        }
        with self._lock:
            self._snapshot = snapshot
        return dict(snapshot)

    def snapshot(self) -> dict | None:
        with self._lock:
            return dict(self._snapshot) if self._snapshot else None


class MoodleAssignmentService:
    """Process-local cache for private Moodle assignment/deadline rows."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot: dict | None = None

    def update(self, assignments: list[dict], source: dict) -> dict:
        normalized = [
            MoodleAssignment.model_validate(item).model_dump(mode="json")
            for item in assignments
        ]
        normalized.sort(key=lambda item: item["due_at"])
        fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        snapshot = {
            "assignments": normalized,
            "assignment_count": len(normalized),
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
