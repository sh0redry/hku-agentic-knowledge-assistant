from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from agents.errors import CapabilityError
from connectors.sis.models import SISTimetableMeeting


HK_TZ = ZoneInfo("Asia/Hong_Kong")
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _time_value(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class TimetableService:
    """Process-local cache and deterministic timetable calculations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._snapshot: dict | None = None

    def update(self, term_label: str, meetings: list[dict], source: dict) -> dict:
        normalized = []
        seen = set()
        for item in meetings:
            meeting = SISTimetableMeeting.model_validate(item).model_dump(mode="json")
            key = tuple(meeting.get(field) for field in (
                "course_code",
                "section",
                "class_number",
                "weekday",
                "start_time",
                "end_time",
                "room",
            ))
            if key in seen:
                continue
            seen.add(key)
            normalized.append(meeting)
        duplicates_removed = len(meetings) - len(normalized)
        fetched_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        snapshot = {
            "term_label": term_label,
            "week_range": source.get("week_range"),
            "timezone": "Asia/Hong_Kong",
            "meetings": normalized,
            "meeting_count": len(normalized),
            "fetched_at": fetched_at,
            "source": source,
            "cache_scope": "process_memory_only",
            "normalization_warnings": (
                [f"Removed {duplicates_removed} duplicate meeting row(s)."]
                if duplicates_removed
                else []
            ),
        }
        with self._lock:
            self._snapshot = snapshot
        return dict(snapshot)

    def snapshot(self, term_label: str | None = None) -> dict:
        with self._lock:
            snapshot = dict(self._snapshot) if self._snapshot else None
        if snapshot is None:
            raise CapabilityError(
                "TIMETABLE_NOT_SYNCED",
                "Synchronize the live SIS weekly timetable before running local calculations.",
            )
        if term_label and snapshot["term_label"] != term_label:
            raise CapabilityError(
                "TIMETABLE_TERM_MISMATCH",
                f"The cached timetable is '{snapshot['term_label']}', not '{term_label}'.",
            )
        return snapshot

    def optional_snapshot(self) -> dict | None:
        """Return the private process-local snapshot without turning absence into an error."""
        with self._lock:
            return dict(self._snapshot) if self._snapshot else None

    def next_class(
        self,
        *,
        term_label: str | None,
        as_of: datetime | None,
        days_ahead: int,
    ) -> dict:
        snapshot = self.snapshot(term_label)
        current = as_of or datetime.now(HK_TZ)
        if current.tzinfo is None:
            current = current.replace(tzinfo=HK_TZ)
        else:
            current = current.astimezone(HK_TZ)
        candidates = []
        for day_offset in range(days_ahead + 1):
            date = current.date() + timedelta(days=day_offset)
            weekday = WEEKDAYS[date.weekday()]
            for meeting in snapshot["meetings"]:
                if meeting["weekday"] != weekday:
                    continue
                hour, minute = (int(part) for part in meeting["start_time"].split(":"))
                starts_at = datetime(
                    date.year, date.month, date.day, hour, minute, tzinfo=HK_TZ
                )
                if starts_at >= current:
                    candidates.append((starts_at, meeting))
        candidates.sort(key=lambda item: item[0])
        next_item = None
        if candidates:
            starts_at, meeting = candidates[0]
            next_item = {
                **meeting,
                "starts_at": starts_at.isoformat(),
                "minutes_until": max(0, int((starts_at - current).total_seconds() // 60)),
            }
        return {
            "read_only": True,
            "derived_locally": True,
            "browser_interactions_performed": False,
            "domain_writes_performed": 0,
            "term_label": snapshot["term_label"],
            "timezone": "Asia/Hong_Kong",
            "as_of": current.isoformat(),
            "days_ahead": days_ahead,
            "next_class": next_item,
            "source_fetched_at": snapshot["fetched_at"],
            "warnings": [
                "This is a recurring weekly projection; teaching weeks, reading weeks, public holidays, and class suspensions are not yet validated."
            ],
        }

    def free_slots(
        self,
        *,
        term_label: str | None,
        weekdays: list[str],
        window_start: str,
        window_end: str,
        minimum_minutes: int,
    ) -> dict:
        snapshot = self.snapshot(term_label)
        start = _minutes(window_start)
        end = _minutes(window_end)
        slots = []
        for weekday in weekdays:
            occupied = sorted(
                (
                    max(start, _minutes(item["start_time"])),
                    min(end, _minutes(item["end_time"])),
                )
                for item in snapshot["meetings"]
                if item["weekday"] == weekday
                and _minutes(item["end_time"]) > start
                and _minutes(item["start_time"]) < end
            )
            merged: list[list[int]] = []
            for interval_start, interval_end in occupied:
                if not merged or interval_start > merged[-1][1]:
                    merged.append([interval_start, interval_end])
                else:
                    merged[-1][1] = max(merged[-1][1], interval_end)
            cursor = start
            for interval_start, interval_end in merged:
                if interval_start - cursor >= minimum_minutes:
                    slots.append(
                        {
                            "weekday": weekday,
                            "start_time": _time_value(cursor),
                            "end_time": _time_value(interval_start),
                            "duration_minutes": interval_start - cursor,
                        }
                    )
                cursor = max(cursor, interval_end)
            if end - cursor >= minimum_minutes:
                slots.append(
                    {
                        "weekday": weekday,
                        "start_time": _time_value(cursor),
                        "end_time": _time_value(end),
                        "duration_minutes": end - cursor,
                    }
                )
        return {
            "read_only": True,
            "derived_locally": True,
            "browser_interactions_performed": False,
            "domain_writes_performed": 0,
            "term_label": snapshot["term_label"],
            "timezone": "Asia/Hong_Kong",
            "window": {"start_time": window_start, "end_time": window_end},
            "minimum_minutes": minimum_minutes,
            "free_slots": slots,
            "source_fetched_at": snapshot["fetched_at"],
        }

    def conflicts(self, *, term_label: str | None, candidates: list[dict]) -> dict:
        snapshot = self.snapshot(term_label)
        candidate_meetings = [
            SISTimetableMeeting.model_validate(item).model_dump(mode="json")
            for item in candidates
        ]
        conflicts = []
        for candidate in candidate_meetings:
            for existing in snapshot["meetings"]:
                if candidate["weekday"] != existing["weekday"]:
                    continue
                overlap_start = max(
                    _minutes(candidate["start_time"]), _minutes(existing["start_time"])
                )
                overlap_end = min(
                    _minutes(candidate["end_time"]), _minutes(existing["end_time"])
                )
                if overlap_start < overlap_end:
                    conflicts.append(
                        {
                            "candidate": candidate,
                            "existing": existing,
                            "overlap": {
                                "start_time": _time_value(overlap_start),
                                "end_time": _time_value(overlap_end),
                                "duration_minutes": overlap_end - overlap_start,
                            },
                        }
                    )
        return {
            "read_only": True,
            "derived_locally": True,
            "browser_interactions_performed": False,
            "domain_writes_performed": 0,
            "term_label": snapshot["term_label"],
            "timezone": "Asia/Hong_Kong",
            "candidate_meetings": candidate_meetings,
            "conflict_count": len(conflicts),
            "has_conflicts": bool(conflicts),
            "conflicts": conflicts,
            "source_fetched_at": snapshot["fetched_at"],
        }
