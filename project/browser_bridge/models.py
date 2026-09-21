from __future__ import annotations

import re
import datetime as datetime_module
from datetime import date, datetime
from urllib.parse import urlparse
from typing import Annotated, Literal

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
                "https://booking.lib.hku.hk",
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
    sso_entry_candidate_count: int = Field(default=0, ge=0, le=20)
    sso_entry_available: bool = False


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
    portal_session_reused: bool = False
    moodle_session_reused: bool = False
    sso_interactions_performed: bool = False
    credentials_entered: Literal[False] = False
    mfa_interactions_performed: Literal[False] = False
    steps: list[Literal[
        "portal_to_moodle",
        "moodle_portal_sso_started",
        "moodle_tab_reused",
        "moodle_dashboard_tab_reused",
        "moodle_fixed_route_to_dashboard",
        "target_already_open",
    ]] = Field(min_length=1, max_length=4)
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


class LibraryResearchResult(StrictMessage):
    record_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    title: str = Field(min_length=1, max_length=500)
    resource_type: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    metadata: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=4
    )
    availability_label: str | None = Field(default=None, max_length=500)
    detail_url: str = Field(min_length=20, max_length=1000)

    @field_validator("detail_url")
    @classmethod
    def validate_detail_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "julac-hku.primo.exlibrisgroup.com"
            or parsed.path != "/discovery/fulldisplay"
        ):
            raise ValueError("Library detail URL must use the fixed Find@HKUL route.")
        allowed = {"docid", "vid", "lang"}
        from urllib.parse import parse_qs
        if set(parse_qs(parsed.query)) - allowed:
            raise ValueError("Library detail URL contains an unapproved query field.")
        return value


class LibraryResearchDiagnostics(StrictMessage):
    parser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=20)
    results_marker_found: bool
    empty_results_marker_found: bool = False
    result_candidate_count: int = Field(ge=0, le=1000)
    parsed_result_count: int = Field(ge=0, le=1000)
    incomplete_result_candidate_count: int = Field(ge=0, le=1000)
    unsafe_result_url_candidate_count: int = Field(ge=0, le=1000)
    missing_result_record_id_candidate_count: int = Field(default=0, ge=0, le=1000)
    missing_result_title_candidate_count: int = Field(default=0, ge=0, le=1000)
    missing_result_detail_url_candidate_count: int = Field(default=0, ge=0, le=1000)


class LibraryResearchSnapshot(StrictMessage):
    origin: Literal["https://julac-hku.primo.exlibrisgroup.com"]
    logged_in: bool | None = None
    page_kind: Literal["catalog_results"]
    result_count: int = Field(ge=0, le=20)
    results: list[LibraryResearchResult] = Field(default_factory=list, max_length=20)
    diagnostics: LibraryResearchDiagnostics

    @model_validator(mode="after")
    def validate_result_counts(self):
        if self.result_count != len(self.results):
            raise ValueError("Library result count does not match the structured rows.")
        if self.diagnostics.parsed_result_count != len(self.results):
            raise ValueError("Library parser count does not match the structured rows.")
        return self


class LibraryResearchNavigationResult(StrictMessage):
    read_only: Literal[True]
    navigation_only: Literal[True]
    library_write_requests_sent: Literal[0]
    navigation_interactions_performed: bool
    target_origin: Literal["https://julac-hku.primo.exlibrisgroup.com"]
    target_page_kind: Literal["catalog_results"]
    steps: list[Literal["library_fixed_route_to_research_results"]] = Field(min_length=1, max_length=1)
    snapshot: LibraryResearchSnapshot


class LibraryHoursPeriod(StrictMessage):
    period_label: str = Field(min_length=1, max_length=120)
    hours_label: str = Field(min_length=1, max_length=200)
    status: Literal["open", "closed"]


class LibraryHoursLocation(StrictMessage):
    name: str = Field(min_length=1, max_length=200)
    periods: list[LibraryHoursPeriod] = Field(min_length=1, max_length=14)


class LibraryHoursDiagnostics(StrictMessage):
    parser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=20)
    hours_marker_found: bool
    empty_state_found: bool
    row_count: int = Field(ge=0, le=1000)
    location_candidate_count: int = Field(ge=0, le=200)
    parsed_location_count: int = Field(ge=0, le=200)
    duplicate_location_candidate_count: int = Field(ge=0, le=200)
    placeholder_location_count: int = Field(ge=0, le=200)


class LibraryHoursSnapshot(StrictMessage):
    origin: Literal["https://lib.hku.hk"]
    logged_in: bool | None = None
    page_kind: Literal["library_hours"]
    hours_available: bool
    location_count: int = Field(ge=0, le=200)
    locations: list[LibraryHoursLocation] = Field(default_factory=list, max_length=200)
    source_url: Literal["https://lib.hku.hk/general/hours/"]
    diagnostics: LibraryHoursDiagnostics

    @model_validator(mode="after")
    def validate_hours_counts(self):
        if self.location_count != len(self.locations):
            raise ValueError("Library hours count does not match the structured rows.")
        if self.diagnostics.parsed_location_count != len(self.locations):
            raise ValueError("Library hours parser count does not match the structured rows.")
        if self.hours_available != bool(self.locations):
            raise ValueError("Library hours availability does not match the structured rows.")
        return self


class LibraryHoursNavigationResult(StrictMessage):
    read_only: Literal[True]
    navigation_only: Literal[True]
    library_write_requests_sent: Literal[0]
    navigation_interactions_performed: bool
    target_origin: Literal["https://lib.hku.hk"]
    target_page_kind: Literal["library_hours"]
    steps: list[Literal["library_fixed_route_to_hours"]] = Field(min_length=1, max_length=1)
    snapshot: LibraryHoursSnapshot


class LibraryResearchMetadataField(StrictMessage):
    label: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=1000)


class LibraryResearchAccessOption(StrictMessage):
    kind: Literal["online", "physical", "unknown"]
    availability: Literal["available", "unavailable", "unknown"]
    label: str = Field(min_length=1, max_length=500)


class LibraryResearchItemDiagnostics(StrictMessage):
    parser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=20)
    detail_marker_found: bool
    record_id_found: bool
    title_found: bool
    metadata_field_count: int = Field(ge=0, le=20)
    access_option_candidate_count: int = Field(ge=0, le=1000)
    parsed_access_option_count: int = Field(ge=0, le=30)
    unsafe_access_link_candidate_count: int = Field(ge=0, le=1000)


class LibraryResearchItemSnapshot(StrictMessage):
    origin: Literal["https://julac-hku.primo.exlibrisgroup.com"]
    logged_in: bool | None = None
    page_kind: Literal["catalog_item"]
    record_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    title: str = Field(min_length=1, max_length=500)
    resource_type: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    metadata: list[LibraryResearchMetadataField] = Field(default_factory=list, max_length=20)
    access_options: list[LibraryResearchAccessOption] = Field(default_factory=list, max_length=30)
    detail_url: str = Field(min_length=20, max_length=1000)
    diagnostics: LibraryResearchItemDiagnostics

    @field_validator("detail_url")
    @classmethod
    def validate_detail_url(cls, value: str) -> str:
        return LibraryResearchResult.validate_detail_url(value)

    @model_validator(mode="after")
    def validate_detail_counts(self):
        if self.diagnostics.metadata_field_count != len(self.metadata):
            raise ValueError("Library item metadata count does not match the structured fields.")
        if self.diagnostics.parsed_access_option_count != len(self.access_options):
            raise ValueError("Library access-option count does not match the structured rows.")
        return self


class LibraryResearchItemNavigationResult(StrictMessage):
    read_only: Literal[True]
    navigation_only: Literal[True]
    library_write_requests_sent: Literal[0]
    navigation_interactions_performed: bool
    licensed_full_text_opened: Literal[0]
    target_origin: Literal["https://julac-hku.primo.exlibrisgroup.com"]
    target_page_kind: Literal["catalog_item"]
    steps: list[Literal["library_fixed_route_to_research_item"]] = Field(min_length=1, max_length=1)
    snapshot: LibraryResearchItemSnapshot


class LibrarySpaceSlot(StrictMessage):
    floor: str | None = Field(default=None, max_length=80)
    room: str | None = Field(default=None, max_length=200)
    start_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    status: Literal["available"]


class LibrarySpaceDiagnostics(StrictMessage):
    parser_version: str = Field(pattern=r"^\d+\.\d+\.\d+$", max_length=20)
    availability_marker_found: bool
    availability_legend_found: bool = False
    booked_legend_found: bool = False
    table_matrix_found: bool = False
    slot_candidate_count: int = Field(ge=0, le=10000)
    parsed_available_slot_count: int = Field(ge=0, le=1000)
    incomplete_available_slot_candidate_count: int = Field(ge=0, le=1000)


class LibrarySpaceSnapshot(StrictMessage):
    origin: Literal["https://booking.lib.hku.hk"]
    logged_in: Literal[True]
    page_kind: Literal["space_availability"]
    date: datetime_module.date | None = None
    available_slot_count: int = Field(ge=0, le=200)
    available_slots: list[LibrarySpaceSlot] = Field(default_factory=list, max_length=200)
    diagnostics: LibrarySpaceDiagnostics

    @model_validator(mode="after")
    def validate_slot_counts(self):
        if self.available_slot_count != len(self.available_slots):
            raise ValueError("Library slot count does not match the structured rows.")
        if self.diagnostics.parsed_available_slot_count != len(self.available_slots):
            raise ValueError("Library slot parser count does not match the structured rows.")
        return self


class LibrarySpaceNavigationResult(StrictMessage):
    read_only: Literal[True]
    navigation_only: Literal[True]
    library_write_requests_sent: Literal[0]
    booking_writes_performed: Literal[0]
    navigation_interactions_performed: bool
    target_origin: Literal["https://booking.lib.hku.hk"]
    target_page_kind: Literal["space_availability"]
    facility_type: Literal["single_study_room", "studio_editing_room", "study_table"]
    steps: list[Literal["library_fixed_route_to_space_availability"]] = Field(min_length=1, max_length=1)
    snapshot: LibrarySpaceSnapshot


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
