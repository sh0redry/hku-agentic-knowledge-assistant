from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from services.moodle import MoodleAssignmentService
from services.timetable import TimetableService, WEEKDAYS


HK_TZ = ZoneInfo("Asia/Hong_Kong")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=HK_TZ).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def _parsed(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(result)


def _age_minutes(fetched_at: str | None, current: datetime) -> int | None:
    fetched = _parsed(fetched_at)
    if fetched is None:
        return None
    return max(0, int((current - fetched).total_seconds() // 60))


class DailyBriefingService:
    """Compose private process-local HKU data without browser interaction."""

    def __init__(
        self,
        timetable: TimetableService,
        assignments: MoodleAssignmentService,
    ) -> None:
        self.timetable = timetable
        self.assignments = assignments

    def build(
        self,
        *,
        term_label: str | None,
        as_of: datetime | None,
        days_ahead: int,
        max_cache_age_minutes: int,
    ) -> dict:
        current_utc = _utc(as_of or datetime.now(timezone.utc))
        cache_checked_at = datetime.now(timezone.utc)
        current_hk = current_utc.astimezone(HK_TZ)
        ends_at = current_utc + timedelta(days=days_ahead)
        source_status: dict[str, dict] = {}
        warnings = [
            "Class times are recurring weekly projections; teaching weeks, holidays, and class suspensions are not yet validated."
        ]

        timetable_snapshot = self.timetable.optional_snapshot()
        remaining_classes: list[dict] = []
        next_class = None
        if timetable_snapshot is None:
            source_status["timetable"] = {"status": "missing", "fetched_at": None}
        else:
            age = _age_minutes(timetable_snapshot.get("fetched_at"), cache_checked_at)
            observed_term = timetable_snapshot.get("term_label")
            if term_label and observed_term != term_label:
                status = "term_mismatch"
            elif age is None or age > max_cache_age_minutes:
                status = "stale"
            else:
                status = "ready"
            source_status["timetable"] = {
                "status": status,
                "fetched_at": timetable_snapshot.get("fetched_at"),
                "age_minutes": age,
                "term_label": observed_term,
            }
            if status == "ready":
                weekday = WEEKDAYS[current_hk.weekday()]
                for meeting in timetable_snapshot.get("meetings", []):
                    hour, minute = (int(part) for part in meeting["start_time"].split(":"))
                    starts_at = current_hk.replace(
                        hour=hour, minute=minute, second=0, microsecond=0
                    )
                    if meeting["weekday"] == weekday and starts_at >= current_hk:
                        remaining_classes.append(
                            {
                                **meeting,
                                "starts_at": starts_at.isoformat(),
                                "minutes_until": int(
                                    (starts_at - current_hk).total_seconds() // 60
                                ),
                            }
                        )
                remaining_classes.sort(key=lambda item: item["starts_at"])
                next_result = self.timetable.next_class(
                    term_label=term_label,
                    as_of=current_hk,
                    days_ahead=days_ahead,
                )
                next_class = next_result["next_class"]

        assignment_snapshot = self.assignments.snapshot()
        upcoming_assignments: list[dict] = []
        if assignment_snapshot is None:
            source_status["moodle_assignments"] = {
                "status": "missing",
                "fetched_at": None,
            }
        else:
            age = _age_minutes(assignment_snapshot.get("fetched_at"), cache_checked_at)
            window = (assignment_snapshot.get("source") or {}).get("window") or {}
            coverage_end = _parsed(window.get("ends_at"))
            if age is None or age > max_cache_age_minutes:
                status = "stale"
            elif coverage_end is None or coverage_end < ends_at:
                status = "insufficient_coverage"
            else:
                status = "ready"
            source_status["moodle_assignments"] = {
                "status": status,
                "fetched_at": assignment_snapshot.get("fetched_at"),
                "age_minutes": age,
                "coverage_ends_at": coverage_end.isoformat() if coverage_end else None,
            }
            if status == "ready":
                for item in assignment_snapshot.get("assignments", []):
                    due_at = _parsed(item.get("due_at"))
                    if due_at and current_utc <= due_at <= ends_at:
                        upcoming_assignments.append(item)
                upcoming_assignments.sort(key=lambda item: item["due_at"])

        for source, details in source_status.items():
            if details["status"] != "ready":
                warnings.append(f"Source '{source}' is {details['status']}; its private rows were omitted.")

        deferred_sources = {
            "portal_notices": "not_implemented",
            "exam_status": "not_implemented",
            "library_due_items": "not_implemented",
        }
        complete = all(item["status"] == "ready" for item in source_status.values())
        return {
            "read_only": True,
            "derived_locally": True,
            "browser_interactions_performed": False,
            "domain_writes_performed": 0,
            "as_of": current_hk.isoformat(),
            "timezone": "Asia/Hong_Kong",
            "days_ahead": days_ahead,
            "ends_at": ends_at.astimezone(HK_TZ).isoformat(),
            "complete": complete,
            "source_status": source_status,
            "deferred_sources": deferred_sources,
            "next_class": next_class,
            "remaining_classes_today": remaining_classes,
            "upcoming_assignments": upcoming_assignments,
            "counts": {
                "remaining_classes_today": len(remaining_classes),
                "upcoming_assignments": len(upcoming_assignments),
                "ready_sources": sum(
                    item["status"] == "ready" for item in source_status.values()
                ),
            },
            "warnings": warnings,
        }
