from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urlparse
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from browser_bridge.security import sanitize_path

from connectors.sis.models import CourseSelection, SISExamEntry, SISTimetableMeeting


class StrictMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrowserTabState(StrictMessage):
    bound: bool = False
    origin: Literal[
        "https://hkuportal.hku.hk",
        "https://studentportal.hku.hk",
        "https://sis-main.hku.hk",
        "https://sweb.hku.hk",
        "https://moodle.hku.hk",
    ] | None = None
    logged_in: bool | None = None
    page_kind: Literal[
        "portal_login",
        "portal_home",
        "login",
        "home",
        "term_selection",
        "cart",
        "status",
        "exam_schedule",
        "weekly_timetable",
        "dashboard",
        "course",
        "blocked",
        "unknown",
    ] = "unknown"
    term_label: str | None = Field(default=None, max_length=100)
    course_count: int = Field(default=0, ge=0, le=200)
    temporary_course_count: int = Field(default=0, ge=0, le=200)
    schedule_course_count: int = Field(default=0, ge=0, le=200)
    available_terms: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("available_terms")
    @classmethod
    def validate_available_terms(cls, value: list[str]) -> list[str]:
        pattern = r"^\d{4}-\d{2}\s+Sem\s+[12]$"
        if any(not re.fullmatch(pattern, item) for item in value):
            raise ValueError("Invalid SIS term label in browser snapshot.")
        return value


class BrowserTargetState(StrictMessage):
    system: Literal["portal", "sis", "timetable", "moodle", "library"]
    origin: Literal[
        "https://hkuportal.hku.hk",
        "https://studentportal.hku.hk",
        "https://sis-main.hku.hk",
        "https://sweb.hku.hk",
        "https://moodle.hku.hk",
        "https://julac-hku.primo.exlibrisgroup.com",
        "https://lib.hku.hk",
    ]
    path: str = Field(default="/", min_length=1, max_length=300)
    logged_in: bool | None = None
    page_kind: str = Field(default="unknown", pattern=r"^[a-z][a-z0-9_]{0,39}$")
    parser_version: str | None = Field(
        default=None, pattern=r"^\d+\.\d+\.\d+$", max_length=20
    )
    active: bool = False
    safe_for_writes: Literal[False] = False

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return sanitize_path(value)

    @model_validator(mode="after")
    def validate_system_origin_pair(self):
        allowed_origins = {
            "portal": {
                "https://hkuportal.hku.hk",
                "https://studentportal.hku.hk",
            },
            "sis": {"https://sis-main.hku.hk"},
            "timetable": {"https://sweb.hku.hk"},
            "moodle": {"https://moodle.hku.hk"},
            "library": {
                "https://julac-hku.primo.exlibrisgroup.com",
                "https://lib.hku.hk",
            },
        }
        if self.origin not in allowed_origins[self.system]:
            raise ValueError("Browser target origin is not allowed for the reported system.")
        return self


class SISParserDiagnostics(StrictMessage):
    parser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=20)
    document_count: int = Field(ge=1, le=100)
    table_count: int = Field(ge=0, le=10000)
    row_count: int = Field(ge=0, le=50000)
    cart_marker_found: bool
    schedule_marker_found: bool
    temporary_candidate_count: int = Field(ge=0, le=200)
    schedule_candidate_count: int = Field(ge=0, le=200)
    unclassified_candidate_count: int = Field(ge=0, le=200)
    unclassified_courses: list[CourseSelection] = Field(default_factory=list, max_length=10)


class SISPageSnapshot(BrowserTabState):
    visible_courses: list[CourseSelection] = Field(default_factory=list, max_length=200)
    temporary_courses: list[CourseSelection] = Field(default_factory=list, max_length=200)
    schedule_courses: list[CourseSelection] = Field(default_factory=list, max_length=200)
    schedule_meetings: list[SISTimetableMeeting] = Field(default_factory=list, max_length=1000)
    exam_publication_state: Literal[
        "unavailable", "not_published", "partially_published", "published"
    ] = "unavailable"
    exam_entries: list[SISExamEntry] = Field(default_factory=list, max_length=200)
    diagnostics: SISParserDiagnostics | None = None


class WeeklyTimetableParserDiagnostics(StrictMessage):
    parser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=20)
    term_detection_method: Literal[
        "page_label", "inferred_from_week_start", "unavailable"
    ]
    table_count: int = Field(ge=0, le=10000)
    row_count: int = Field(ge=0, le=50000)
    timetable_marker_found: bool
    meeting_candidate_count: int = Field(ge=0, le=1000)
    parsed_meeting_count: int = Field(ge=0, le=1000)
    unparsed_candidate_count: int = Field(ge=0, le=1000)


class WeeklyTimetableSnapshot(StrictMessage):
    bound: Literal[True]
    origin: Literal["https://sweb.hku.hk"]
    logged_in: bool | None = None
    page_kind: Literal["weekly_timetable", "login", "blocked", "unknown"]
    term_label: str | None = Field(default=None, max_length=100)
    week_range: str | None = Field(default=None, max_length=160)
    meeting_count: int = Field(default=0, ge=0, le=1000)
    meetings: list[SISTimetableMeeting] = Field(default_factory=list, max_length=1000)
    diagnostics: WeeklyTimetableParserDiagnostics


class WeeklyTimetableNavigationResult(StrictMessage):
    read_only: Literal[True]
    navigation_only: Literal[True]
    timetable_write_requests_sent: Literal[0]
    source_origin: Literal[
        "https://hkuportal.hku.hk",
        "https://studentportal.hku.hk",
        "https://sweb.hku.hk",
    ]
    source_page_kind: str = Field(min_length=1, max_length=40)
    target_origin: Literal["https://sweb.hku.hk"]
    target_page_kind: Literal["weekly_timetable"]
    steps: list[Literal[
        "portal_to_weekly_timetable",
        "weekly_timetable_tab_reused",
        "target_already_open",
    ]] = Field(min_length=1, max_length=2)
    snapshot: WeeklyTimetableSnapshot


class MoodleParserDiagnostics(StrictMessage):
    parser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=20)
    dashboard_marker_found: bool
    login_marker_found: bool
    user_menu_found: bool
    course_link_candidate_count: int = Field(ge=0, le=10000)
    timeline_marker_found: bool
    upcoming_marker_found: bool
    todo_marker_found: bool


class MoodleDashboardSnapshot(BrowserTabState):
    origin: Literal["https://moodle.hku.hk"]
    page_kind: Literal["login", "dashboard", "course", "home", "blocked", "unknown"]
    diagnostics: MoodleParserDiagnostics


class MoodleCourse(StrictMessage):
    course_id: str = Field(pattern=r"^\d{1,20}$", max_length=20)
    course_code: str | None = Field(
        default=None, pattern=r"^[A-Z]{2,8}\d{4}[A-Z]?$", max_length=20
    )
    section: str | None = Field(
        default=None, pattern=r"^[0-9]{1,3}[A-Z]{0,2}$", max_length=5
    )
    academic_year: str | None = Field(
        default=None, pattern=r"^20\d{2}-\d{2}$", max_length=7
    )
    name: str = Field(min_length=1, max_length=300)
    state: Literal["current", "past", "future", "unknown"] = "unknown"


class MoodleCourseParserDiagnostics(MoodleParserDiagnostics):
    course_candidate_count: int = Field(ge=0, le=10000)
    parsed_course_count: int = Field(ge=0, le=10000)
    unparsed_course_candidate_count: int = Field(ge=0, le=10000)
    missing_course_id_candidate_count: int = Field(ge=0, le=10000)
    missing_course_name_candidate_count: int = Field(ge=0, le=10000)
    duplicate_course_candidate_count: int = Field(ge=0, le=10000)
    course_placeholder_candidate_count: int = Field(ge=0, le=10000)


class MoodleCourseListSnapshot(BrowserTabState):
    origin: Literal["https://moodle.hku.hk"]
    logged_in: Literal[True]
    page_kind: Literal["dashboard"]
    courses: list[MoodleCourse] = Field(default_factory=list, max_length=200)
    diagnostics: MoodleCourseParserDiagnostics

    @model_validator(mode="after")
    def validate_course_counts(self):
        if self.course_count != len(self.courses):
            raise ValueError("Moodle course count does not match the structured rows.")
        if self.diagnostics.parsed_course_count != len(self.courses):
            raise ValueError("Moodle parser count does not match the structured rows.")
        return self


class MoodleAssignment(StrictMessage):
    event_id: str | None = Field(default=None, pattern=r"^\d{1,20}$", max_length=20)
    module_id: str | None = Field(default=None, pattern=r"^\d{1,20}$", max_length=20)
    course_id: str | None = Field(default=None, pattern=r"^\d{1,20}$", max_length=20)
    course_name: str | None = Field(default=None, min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=300)
    activity_type: Literal["assignment", "quiz", "workshop", "lesson", "forum", "other"]
    due_at: datetime
    due_at_source: Literal[
        "machine",
        "display_text_hong_kong",
        "display_text_hong_kong_inferred_year",
        "display_text_hong_kong_combined_fragments",
        "display_text_hong_kong_combined_fragments_inferred_year",
    ]
    source: Literal["timeline", "upcoming", "todo"]


class MoodleAssignmentParserDiagnostics(MoodleParserDiagnostics):
    assignment_candidate_count: int = Field(ge=0, le=10000)
    parsed_assignment_count: int = Field(ge=0, le=10000)
    unparsed_assignment_candidate_count: int = Field(ge=0, le=10000)
    missing_assignment_title_candidate_count: int = Field(ge=0, le=10000)
    missing_assignment_due_at_candidate_count: int = Field(ge=0, le=10000)
    duplicate_assignment_candidate_count: int = Field(ge=0, le=10000)
    assignment_placeholder_candidate_count: int = Field(ge=0, le=10000)
    visible_assignment_date_text_candidate_count: int = Field(ge=0, le=10000)
    parsed_assignment_display_date_count: int = Field(ge=0, le=10000)
    inferred_assignment_year_count: int = Field(default=0, ge=0, le=10000)
    combined_assignment_date_fragments_parsed_count: int = Field(default=0, ge=0, le=10000)
    assignment_date_text_with_year_count: int = Field(default=0, ge=0, le=10000)
    assignment_date_text_with_month_name_count: int = Field(default=0, ge=0, le=10000)
    assignment_date_text_with_12_hour_time_count: int = Field(default=0, ge=0, le=10000)
    assignment_date_text_with_24_hour_time_count: int = Field(default=0, ge=0, le=10000)
    assignment_date_text_with_relative_day_count: int = Field(default=0, ge=0, le=10000)
    assignment_date_text_with_numeric_date_count: int = Field(default=0, ge=0, le=10000)


class MoodleAssignmentListSnapshot(BrowserTabState):
    origin: Literal["https://moodle.hku.hk"]
    logged_in: Literal[True]
    page_kind: Literal["dashboard"]
    assignment_count: int = Field(ge=0, le=1000)
    assignments: list[MoodleAssignment] = Field(default_factory=list, max_length=1000)
    diagnostics: MoodleAssignmentParserDiagnostics

    @model_validator(mode="after")
    def validate_assignment_counts(self):
        if self.assignment_count != len(self.assignments):
            raise ValueError("Moodle assignment count does not match the structured rows.")
        if self.diagnostics.parsed_assignment_count != len(self.assignments):
            raise ValueError("Moodle assignment parser count does not match the structured rows.")
        return self


class MoodleNavigationResult(StrictMessage):
    read_only: Literal[True]
    navigation_only: Literal[True]
    moodle_write_requests_sent: Literal[0]
    source_origin: Literal[
        "https://hkuportal.hku.hk",
        "https://studentportal.hku.hk",
        "https://moodle.hku.hk",
    ]
    source_page_kind: str = Field(min_length=1, max_length=40)
    target_origin: Literal["https://moodle.hku.hk"]
    target_page_kind: Literal["dashboard"]
    steps: list[Literal[
        "portal_to_moodle",
        "moodle_tab_reused",
        "moodle_dashboard_tab_reused",
        "moodle_fixed_route_to_dashboard",
        "target_already_open",
    ]] = Field(min_length=1, max_length=2)
    snapshot: MoodleDashboardSnapshot


class PortalNavigationDiagnostics(StrictMessage):
    parser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=20)
    sis_entry_candidate_count: int = Field(ge=0, le=20)
    sis_entry_available: bool
    candidate_labels: list[str] = Field(default_factory=list, max_length=5)
    moodle_entry_candidate_count: int = Field(ge=0, le=20)
    moodle_entry_available: bool
    moodle_candidate_labels: list[str] = Field(default_factory=list, max_length=5)


class PortalPageSnapshot(BrowserTabState):
    origin: Literal["https://hkuportal.hku.hk", "https://studentportal.hku.hk"]
    page_kind: Literal["portal_login", "portal_home", "blocked", "unknown"]
    navigation_diagnostics: PortalNavigationDiagnostics


class PortalNotice(StrictMessage):
    title: str = Field(min_length=6, max_length=500)
    published_date: date
    source_label: str | None = Field(default=None, min_length=1, max_length=200)
    url: str = Field(min_length=12, max_length=1000)
    url_query_redacted: bool = False

    @field_validator("url")
    @classmethod
    def validate_notice_url(cls, value: str) -> str:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            hostname == "hku.hk" or hostname.endswith(".hku.hk")
        ):
            raise ValueError("Portal notice URL must remain on an HKU HTTPS host.")
        if parsed.query or parsed.fragment:
            raise ValueError("Portal notice URL must not contain a query or fragment.")
        return value


class PortalNoticeParserDiagnostics(StrictMessage):
    parser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=20)
    news_marker_found: bool
    notice_candidate_count: int = Field(ge=0, le=1000)
    parsed_notice_count: int = Field(ge=0, le=1000)
    unparsed_notice_candidate_count: int = Field(ge=0, le=1000)
    unsafe_notice_url_candidate_count: int = Field(ge=0, le=1000)
    duplicate_notice_candidate_count: int = Field(ge=0, le=1000)


class PortalNoticeListSnapshot(PortalPageSnapshot):
    logged_in: Literal[True]
    page_kind: Literal["portal_home"]
    notice_count: int = Field(ge=0, le=500)
    notices: list[PortalNotice] = Field(default_factory=list, max_length=500)
    diagnostics: PortalNoticeParserDiagnostics

    @model_validator(mode="after")
    def validate_notice_counts(self):
        if self.notice_count != len(self.notices):
            raise ValueError("Portal notice count does not match the structured rows.")
        if self.diagnostics.parsed_notice_count != len(self.notices):
            raise ValueError("Portal notice parser count does not match the structured rows.")
        return self


class SISNavigationResult(StrictMessage):
    read_only: Literal[True]
    navigation_only: Literal[True]
    sis_write_requests_sent: Literal[0]
    source_origin: Literal[
        "https://hkuportal.hku.hk",
        "https://studentportal.hku.hk",
        "https://sis-main.hku.hk",
    ]
    source_page_kind: str = Field(min_length=1, max_length=40)
    target_origin: Literal["https://sis-main.hku.hk"]
    target_page_kind: Literal["cart"]
    sis_session_reused: bool = False
    steps: list[Literal[
        "portal_to_sis",
        "sis_fixed_route_to_enrollment_add_classes",
        "sis_select_term",
        "target_already_open",
    ]] = Field(min_length=1, max_length=3)
    snapshot: SISPageSnapshot


class PairMessage(StrictMessage):
    type: Literal["pair"]
    token: str = Field(min_length=20, max_length=200)
    extension_version: str = Field(min_length=1, max_length=40)


class HeartbeatMessage(StrictMessage):
    type: Literal["heartbeat"]
    tab: BrowserTabState | None = None
    targets: list[BrowserTargetState] = Field(default_factory=list, max_length=8)


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
