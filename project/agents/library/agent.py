from __future__ import annotations

import hashlib
import ipaddress
import json
from datetime import date as date_type, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import config
from agents.base import BaseCapability
from agents.errors import CapabilityError, ExecutionUnknownError, PolicyDeniedError
from agents.models import (
    CapabilityManifest,
    CapabilityMode,
    ConfirmationMode,
    ExecutionContext,
    RiskLevel,
    utc_now,
)
from browser_bridge.service import BrowserBridgeError
from connectors.sis.browser import BrowserSISConnector
from services.library_booking import LibraryBookingPreviewRegistry


MAIN_LIBRARY_AVAILABILITY_TARGETS = [
    {"facility_type": "single_study_room", "location": "Main Library", "booking_facility_type": "Single Study Room (3 sessions)"},
    {"facility_type": "av_group_viewing_room", "location": "Main Library", "booking_facility_type": "AV Group Viewing Room"},
    {"facility_type": "communal_virtual_pc", "location": "Main Library", "booking_facility_type": "Communal Virtual PC"},
    {"facility_type": "computer", "location": "Main Library", "booking_facility_type": "Computer"},
    {"facility_type": "computer_in_lic", "location": "Main Library", "booking_facility_type": "Computer in LIC"},
    {"facility_type": "engraving_cutting_computer", "location": "Main Library", "booking_facility_type": "computer-controlled machines for engraving/cutting"},
    {"facility_type": "concept_and_creation_room", "location": "Main Library", "booking_facility_type": "Concept and Creation Room"},
    {"facility_type": "discussion_room", "location": "Main Library", "booking_facility_type": "Discussion Room"},
    {"facility_type": "microform_scanner", "location": "Main Library", "booking_facility_type": "Special Collections - Microform Scanner"},
    {"facility_type": "overhead_scanner", "location": "Main Library", "booking_facility_type": "Special Collections - Overhead Scanner"},
    {"facility_type": "research_desk", "location": "Main Library", "booking_facility_type": "Special Collections - Research Desk"},
    {"facility_type": "studio_editing_room", "location": "Main Library", "booking_facility_type": "Studio and Editing Room"},
    {"facility_type": "study_table", "location": "Main Library", "booking_facility_type": "Study Table"},
    {"facility_type": "study_table_deep_quiet", "location": "Main Library", "booking_facility_type": "Study Table (Deep Quiet)"},
    {"facility_type": "study_room", "location": "Chi Wah Learning Commons", "booking_facility_type": "Study Room"},
]
BOOKING_PREVIEW_FACILITY_TYPES = frozenset({
    "single_study_room", "studio_editing_room", "study_table", "study_room",
    "discussion_room",
})
SUPERVISED_BOOKING_FACILITY_TYPES = frozenset({"single_study_room", "discussion_room"})
SUPERVISED_BOOKING_ROUTES = {
    "single_study_room": ("Main Library", "Single Study Room (3 sessions)"),
    "discussion_room": ("Main Library", "Discussion Room"),
}


class LibraryResearchSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=200)
    field: Literal["any", "title", "author", "subject"] = "any"
    scope: Literal["hku", "everything"] = "hku"
    limit: int = Field(default=10, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Library query must contain at least two visible characters.")
        return normalized


class LibrarySpaceAvailabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_type: Literal[
        "single_study_room", "av_group_viewing_room", "communal_virtual_pc",
        "computer", "computer_in_lic", "engraving_cutting_computer",
        "concept_and_creation_room", "discussion_room", "microform_scanner",
        "overhead_scanner", "research_desk", "studio_editing_room",
        "study_table", "study_table_deep_quiet", "study_room"
    ]
    date: date_type


class LibrarySpaceBookingPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_type: Literal[
        "single_study_room", "studio_editing_room", "study_table", "study_room",
        "discussion_room",
    ]
    date: date_type
    floor: str | None = Field(default=None, min_length=1, max_length=80)
    room: str = Field(min_length=1, max_length=200)
    start_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    eligibility_category: Literal[
        "current_hku_students",
        "current_hku_staff",
        "current_hku_space_students",
        "current_hku_space_staff",
        "hku_alumni",
    ]

    @field_validator("floor", "room")
    @classmethod
    def normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Booking target labels must contain visible characters.")
        return normalized

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time.")
        return self


class LibrarySpaceBookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_acceptance_acknowledged: Literal[True]
    discussion_room_rules_acknowledged: Literal[True] | None = None


class LibraryFacilityListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LibraryHoursAndLocationsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LibraryResearchRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")


def _translate_browser_error(exc: BrowserBridgeError) -> CapabilityError:
    if exc.code in {"COMMAND_NOT_ALLOWED", "PAGE_SCRIPT_UNAVAILABLE"}:
        return CapabilityError(
            "EXTENSION_UPDATE_REQUIRED",
            "Reload HKU AGENTS Browser Bridge 0.17.12 before using HKUL tools.",
        )
    return CapabilityError(exc.code, str(exc))


def hku_booking_today(now: datetime | None = None) -> date_type:
    instant = now or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    return instant.astimezone(ZoneInfo("Asia/Hong_Kong")).date()


def require_supported_booking_date(requested: date_type) -> None:
    today = hku_booking_today()
    tomorrow = today + timedelta(days=1)
    if requested not in {today, tomorrow}:
        raise CapabilityError(
            "LIBRARY_SPACE_DATE_OUT_OF_WINDOW",
            f"HKUL availability for the supported facilities can be searched for {today} or {tomorrow} (Hong Kong time); requested {requested}.",
            {"requested_date": requested.isoformat(), "today": today.isoformat(), "tomorrow": tomorrow.isoformat()},
        )


def library_booking_host_is_loopback(host: str | None = None) -> bool:
    """F2 writes are allowed only when the application binds to loopback."""
    value = (host if host is not None else config.APP_HOST).strip().strip("[]")
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


class LibraryResearchSearchCapability(BaseCapability):
    input_model = LibraryResearchSearchRequest
    manifest = CapabilityManifest(
        id="library.research.search",
        version=1,
        agent="library",
        title="Search HKUL research resources",
        description=(
            "Open a fixed Find@HKUL search route and read up to 20 visible bibliographic "
            "results. This may navigate a browser tab but never signs in, saves favorites, "
            "requests an item, or opens licensed full text."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_public_read_only",
        input_schema="LibraryResearchSearchRequest",
        output_schema="LibraryResearchSearchResult",
            timeout_seconds=35,
    )

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

    def persisted_input(self, validated_input: LibraryResearchSearchRequest) -> dict:
        return {
            "field": validated_input.field,
            "scope": validated_input.scope,
            "limit": validated_input.limit,
            "query_persisted": False,
        }

    def persisted_result(self, result: dict) -> dict:
        return {
            "read_only": True,
            "library_writes_performed": 0,
            "result_count": result.get("result_count", 0),
            "private_query_or_result_details_persisted": False,
        }

    async def execute(self, validated_input: LibraryResearchSearchRequest, context: ExecutionContext) -> dict:
        try:
            navigation = await self.connector.search_library_research(
                validated_input.model_dump(mode="json")
            )
        except BrowserBridgeError as exc:
            raise _translate_browser_error(exc) from exc
        snapshot = navigation["snapshot"]
        diagnostics = snapshot["diagnostics"]
        if diagnostics["parser_version"] != "0.2.2":
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.17.12.")
        if diagnostics["incomplete_result_candidate_count"] or diagnostics["unsafe_result_url_candidate_count"]:
            raise CapabilityError(
                "LIBRARY_RESEARCH_PARSE_INCOMPLETE",
                "One or more visible Find@HKUL results could not be parsed safely.",
                {"diagnostics": diagnostics},
            )
        if not diagnostics["results_marker_found"]:
            raise CapabilityError("LIBRARY_SEARCH_NOT_READY", "Find@HKUL search results did not become ready.")
        return {
            "read_only": True,
            "systems_contacted": ["find_hkul"],
            "navigation_interactions_performed": navigation["navigation_interactions_performed"],
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "library_writes_performed": 0,
            "account_data_read": False,
            "licensed_full_text_opened": 0,
            "query": validated_input.model_dump(mode="json"),
            "result_count": snapshot["result_count"],
            "results": snapshot["results"],
            "diagnostics": diagnostics,
            "navigation": {key: value for key, value in navigation.items() if key != "snapshot"},
        }


class LibraryResearchItemCapability(BaseCapability):
    input_model = LibraryResearchRecordRequest
    manifest = CapabilityManifest(
        id="library.research.item",
        version=1,
        agent="library",
        title="Read a Find@HKUL item",
        description=(
            "Open the fixed Find@HKUL full-display route for one stable record ID and "
            "read visible bibliographic fields. It never opens licensed full text, signs "
            "in, saves, requests, or exports authentication links."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_public_read_only",
        input_schema="LibraryResearchRecordRequest",
        output_schema="LibraryResearchItemResult",
            timeout_seconds=35,
    )

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

    def persisted_result(self, result: dict) -> dict:
        return {
            "read_only": True,
            "library_writes_performed": 0,
            "record_id": result.get("record_id"),
            "metadata_field_count": len(result.get("metadata", [])),
            "private_item_details_persisted": False,
        }

    async def execute(self, validated_input: LibraryResearchRecordRequest, context: ExecutionContext) -> dict:
        try:
            navigation = await self.connector.read_library_research_item(
                validated_input.model_dump(mode="json")
            )
        except BrowserBridgeError as exc:
            raise _translate_browser_error(exc) from exc
        snapshot = navigation["snapshot"]
        diagnostics = snapshot["diagnostics"]
        if diagnostics["parser_version"] != "0.2.2":
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.17.12.")
        if not diagnostics["detail_marker_found"] or not diagnostics["record_id_found"] or not diagnostics["title_found"]:
            raise CapabilityError(
                "LIBRARY_ITEM_PARSE_INCOMPLETE",
                "The requested Find@HKUL item could not be parsed safely.",
                {"diagnostics": diagnostics},
            )
        return {
            "read_only": True,
            "systems_contacted": ["find_hkul"],
            "navigation_interactions_performed": navigation["navigation_interactions_performed"],
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "library_writes_performed": 0,
            "account_data_read": False,
            "licensed_full_text_opened": 0,
            "record_id": snapshot["record_id"],
            "title": snapshot["title"],
            "resource_type": snapshot["resource_type"],
            "metadata": snapshot["metadata"],
            "detail_url": snapshot["detail_url"],
            "diagnostics": diagnostics,
            "navigation": {key: value for key, value in navigation.items() if key != "snapshot"},
        }


class LibraryResearchAccessOptionsCapability(BaseCapability):
    input_model = LibraryResearchRecordRequest
    manifest = CapabilityManifest(
        id="library.research.access_options",
        version=1,
        agent="library",
        title="Read Find@HKUL access options",
        description=(
            "Read visible online/physical availability labels for one stable Find@HKUL "
            "record ID. It suppresses proxy and authentication URLs and never opens full text."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_public_read_only",
        input_schema="LibraryResearchRecordRequest",
        output_schema="LibraryResearchAccessOptionsResult",
        timeout_seconds=35,
    )

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

    def persisted_result(self, result: dict) -> dict:
        return {
            "read_only": True,
            "library_writes_performed": 0,
            "record_id": result.get("record_id"),
            "access_option_count": result.get("access_option_count", 0),
            "private_access_details_persisted": False,
        }

    async def execute(self, validated_input: LibraryResearchRecordRequest, context: ExecutionContext) -> dict:
        try:
            navigation = await self.connector.read_library_research_access_options(
                validated_input.model_dump(mode="json")
            )
        except BrowserBridgeError as exc:
            raise _translate_browser_error(exc) from exc
        snapshot = navigation["snapshot"]
        diagnostics = snapshot["diagnostics"]
        if diagnostics["parser_version"] != "0.2.2":
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.17.12.")
        if not diagnostics["detail_marker_found"] or not diagnostics["record_id_found"] or not diagnostics["title_found"]:
            raise CapabilityError(
                "LIBRARY_ACCESS_PARSE_INCOMPLETE",
                "The requested Find@HKUL access options could not be parsed safely.",
                {"diagnostics": diagnostics},
            )
        options = snapshot["access_options"]
        return {
            "read_only": True,
            "systems_contacted": ["find_hkul"],
            "navigation_interactions_performed": navigation["navigation_interactions_performed"],
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "library_writes_performed": 0,
            "account_data_read": False,
            "licensed_full_text_opened": 0,
            "external_access_links_returned": 0,
            "record_id": snapshot["record_id"],
            "title": snapshot["title"],
            "access_option_count": len(options),
            "access_options": options,
            "diagnostics": diagnostics,
            "warnings": [] if options else [
                "No access-option labels were exposed in the current full-display DOM; this does not prove the item is unavailable."
            ],
            "navigation": {key: value for key, value in navigation.items() if key != "snapshot"},
        }


class LibraryFacilityListCapability(BaseCapability):
    input_model = LibraryFacilityListRequest
    manifest = CapabilityManifest(
        id="library.spaces.list_facilities",
        version=1,
        agent="library",
        title="List supported HKUL facilities",
        description=(
            "Return the locally verified catalog and policy summary for HKUL facilities "
            "supported by the availability tool. It performs no browser interaction, slot "
            "selection, booking-form navigation, or reservation write."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.LOW,
        confirmation=ConfirmationMode.NONE,
        required_connections=[],
        availability="available",
        input_schema="LibraryFacilityListRequest",
        output_schema="LibraryFacilityListResult",
        timeout_seconds=5,
    )

    FACILITIES = [
        {
            "facility_type": "single_study_room",
            "name": "Single Study Rooms",
            "location": "Main Library, 4/F",
            "booking_location": "Main Library",
            "booking_facility_type": "Single Study Room (3 sessions)",
            "capacity": 1,
            "equipment": [],
            "eligibility": ["current_hku_students", "current_hku_staff", "current_hku_space_students", "current_hku_space_staff"],
            "availability_search_supported": True,
            "booking_policy": {
                "session_duration_minutes": None,
                "available_session_windows_per_weekday": 3,
                "available_session_windows_per_weekend_or_holiday": 2,
                "advance_booking": "one_session_in_advance",
                "check_in_required": True,
                "release_after_minutes": 60,
                "session_windows": [
                    {"day_group": "monday_to_friday", "windows": ["08:30-13:00", "13:00-18:00", "18:00-22:00"]},
                    {"day_group": "saturday_sunday_public_holidays", "windows": ["09:00-13:00", "13:00-17:00"]},
                ],
                "seasonal_notes": ["The third weekday session ends at 21:00 from June through August."],
            },
        },
        {
            "facility_type": "studio_editing_room",
            "name": "Editing Rooms & Computers (Library Innovation Centre)",
            "location": "Main Library, Library Innovation Centre, 2/F",
            "booking_location": "Main Library",
            "booking_facility_type": "Studio and Editing Room",
            "capacity": None,
            "equipment": ["editing_computer"],
            "eligibility": ["current_hku_students", "current_hku_staff"],
            "availability_search_supported": True,
            "booking_policy": {
                "session_duration_minutes": 60,
                "maximum_minutes_per_day": 180,
                "advance_booking": "one_day_in_advance",
                "check_in_required": True,
                "release_after_minutes": 15,
                "session_windows": [],
                "seasonal_notes": [],
            },
        },
        {
            "facility_type": "study_table",
            "name": "Study Tables",
            "location": "Participating HKUL locations, including reservable Main Library study tables",
            "booking_location": "Main Library",
            "booking_facility_type": "Study Table",
            "capacity": None,
            "equipment": [],
            "eligibility": ["current_hku_students", "current_hku_staff", "current_hku_space_students", "current_hku_space_staff", "hku_alumni"],
            "availability_search_supported": True,
            "booking_policy": {
                "session_duration_minutes": None,
                "maximum_active_sessions": 1,
                "advance_booking": "one_session_in_advance",
                "check_in_required": True,
                "release_after_minutes": 60,
                "session_windows": [
                    {"day_group": "monday_to_friday", "windows": ["08:30-13:00", "13:00-18:00", "18:00-22:00"]},
                    {"day_group": "saturday_sunday_public_holidays", "windows": ["09:00-13:00", "13:00-17:00"]},
                ],
                "seasonal_notes": ["The third weekday session ends at 21:00 from June through August."],
            },
        },
        {
            "facility_type": "study_room",
            "name": "Study Rooms",
            "location": "Chi Wah Learning Commons",
            "booking_location": "Chi Wah Learning Commons",
            "booking_facility_type": "Study Room",
            "capacity": None,
            "equipment": [],
            "eligibility": ["current_hku_students", "current_hku_staff"],
            "availability_search_supported": True,
            "booking_policy": {
                "session_duration_minutes": 60,
                "advance_booking": "not_verified",
                "check_in_required": None,
                "release_after_minutes": None,
                "session_windows": [],
                "seasonal_notes": [
                    "The live booking form identifies this facility as current students/staff only; remaining limits require verification before F2."
                ],
            },
        },
        {
            "facility_type": "discussion_room",
            "name": "Discussion Rooms",
            "location": "Tin Ka Ping Education Library, Main Library, Level 3",
            "booking_location": "Main Library",
            "booking_facility_type": "Discussion Room",
            "capacity": None,
            "equipment": [
                "commercial_grade_tv_panel",
                "webcam_with_builtin_microphone",
                "kvm_switch",
            ],
            "eligibility": [
                "current_hku_students",
                "current_hku_staff",
                "current_hku_space_students",
                "current_hku_space_staff",
            ],
            "availability_search_supported": True,
            "booking_policy": {
                "session_duration_minutes": 60,
                "maximum_sessions_per_day": 2,
                "maximum_minutes_per_day": 120,
                "minimum_patron_count": 2,
                "interleaving_rule": (
                    "Two bookings by the same patron cannot have exactly one unbooked "
                    "session between them; two or more unbooked sessions are allowed."
                ),
                "advance_booking": "one_day_in_advance",
                "check_in_required": True,
                "release_after_minutes": 15,
                "session_windows": [],
                "seasonal_notes": [],
            },
        },
    ]

    def persisted_result(self, result: dict) -> dict:
        return {
            "read_only": True,
            "facility_count": result.get("facility_count", 0),
            "availability_target_count": result.get("availability_target_count", 0),
            "policy_verified_on": result.get("policy_verified_on"),
            "domain_writes_performed": 0,
        }

    async def execute(self, validated_input: LibraryFacilityListRequest, context: ExecutionContext) -> dict:
        availability_targets = [
            {
                **target,
                "availability_search_supported": True,
                "booking_preview_supported": target["facility_type"] in BOOKING_PREVIEW_FACILITY_TYPES,
                "supervised_booking_supported": target["facility_type"] in SUPERVISED_BOOKING_FACILITY_TYPES,
            }
            for target in MAIN_LIBRARY_AVAILABILITY_TARGETS
        ]
        return {
            "read_only": True,
            "derived_locally": True,
            "systems_contacted": [],
            "browser_interactions_performed": False,
            "data_reads_performed": 0,
            "domain_writes_performed": 0,
            "library_writes_performed": 0,
            "booking_writes_performed": 0,
            "slot_selection_performed": False,
            "booking_form_opened": False,
            "facility_count": len(self.FACILITIES),
            "availability_target_count": len(availability_targets),
            "availability_targets": availability_targets,
            "catalog_scope": "allowlisted_availability_targets_and_policy_summaries",
            "facilities": self.FACILITIES,
            "policy_verified_on": "2026-09-24",
            "policy_sources": [
                {"title": "HKUL Book A Space", "url": "https://lib.hku.hk/general/e-form/book-a-space.html"},
                {"title": "HKUL Booking Policy", "url": "https://lib.hku.hk/general/e-form/L3_booking_policy.html"},
                {"title": "HKUL Main Library Level 3", "url": "https://lib.hku.hk/level3/zones.html"},
            ],
            "warnings": [
                "Facility availability and booking policies can change; re-check the cited official policy before acting.",
                "Listing a facility does not establish current eligibility or availability and does not authorize a booking.",
            ],
        }


class LibraryHoursAndLocationsCapability(BaseCapability):
    input_model = LibraryHoursAndLocationsRequest
    manifest = CapabilityManifest(
        id="library.hours_and_locations",
        version=1,
        agent="library",
        title="Read HKUL hours and locations",
        description=(
            "Open the official HKUL current-hours page and read the visible location and "
            "time-period rows. An explicit unavailable state is reported as unavailable, "
            "not interpreted as closure. This performs no account access or library write."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_public_read_only",
        input_schema="LibraryHoursAndLocationsRequest",
        output_schema="LibraryHoursAndLocationsResult",
        timeout_seconds=35,
    )

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

    def persisted_result(self, result: dict) -> dict:
        return {
            "read_only": True,
            "library_writes_performed": 0,
            "hours_available": result.get("hours_available", False),
            "location_count": result.get("location_count", 0),
            "location_hours_persisted": False,
        }

    async def execute(self, validated_input: LibraryHoursAndLocationsRequest, context: ExecutionContext) -> dict:
        try:
            navigation = await self.connector.read_library_hours_and_locations()
        except BrowserBridgeError as exc:
            raise _translate_browser_error(exc) from exc
        snapshot = navigation["snapshot"]
        diagnostics = snapshot["diagnostics"]
        if diagnostics["parser_version"] != "0.1.1":
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.17.12.")
        if not diagnostics["hours_marker_found"]:
            raise CapabilityError("LIBRARY_HOURS_NOT_READY", "The official HKUL opening-hours view is not ready.")
        if not snapshot["hours_available"] and not diagnostics["empty_state_found"]:
            raise CapabilityError(
                "LIBRARY_HOURS_PARSE_INCOMPLETE",
                "The HKUL page exposed neither verified hours nor its explicit unavailable state.",
                {"diagnostics": diagnostics},
            )
        warnings = []
        if diagnostics["empty_state_found"]:
            warnings.append(
                "HKUL explicitly reports that opening hours for the selected date are not available yet; this does not mean the libraries are closed."
            )
        if diagnostics["placeholder_location_count"]:
            warnings.append(
                "One or more placeholder rows contained no open/closed hours and were not returned as locations."
            )
        return {
            "read_only": True,
            "systems_contacted": ["hkul_public"],
            "navigation_interactions_performed": navigation["navigation_interactions_performed"],
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "library_writes_performed": 0,
            "account_data_read": False,
            "hours_available": snapshot["hours_available"],
            "location_count": snapshot["location_count"],
            "locations": snapshot["locations"],
            "source_url": snapshot["source_url"],
            "diagnostics": diagnostics,
            "warnings": warnings,
            "navigation": {key: value for key, value in navigation.items() if key != "snapshot"},
        }

class LibrarySpaceAvailabilityCapability(BaseCapability):
    input_model = LibrarySpaceAvailabilityRequest
    manifest = CapabilityManifest(
        id="library.spaces.search_availability",
        version=1,
        agent="library",
        title="Read HKUL space availability",
        description=(
            "Open the fixed HKUL Book a Space status page, set one exact allow-listed "
            "Location and Facility Type plus the required date, submit Search, and read "
            "the complete visible availability matrix. It never selects a slot, enters "
            "booking details, or submits a reservation."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_authenticated_read_only",
        input_schema="LibrarySpaceAvailabilityRequest",
        output_schema="LibrarySpaceAvailabilityResult",
        timeout_seconds=35,
    )

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

    def persisted_result(self, result: dict) -> dict:
        return {
            "read_only": True,
            "booking_writes_performed": 0,
            "facility_type": result.get("facility_type"),
            "available_slot_count": result.get("available_slot_count", 0),
            "private_availability_details_persisted": False,
        }

    async def execute(self, validated_input: LibrarySpaceAvailabilityRequest, context: ExecutionContext) -> dict:
        require_supported_booking_date(validated_input.date)
        try:
            navigation = await self.connector.search_library_space_availability(
                validated_input.model_dump(mode="json")
            )
        except BrowserBridgeError as exc:
            raise _translate_browser_error(exc) from exc
        snapshot = navigation["snapshot"]
        diagnostics = snapshot["diagnostics"]
        if diagnostics["parser_version"] != "0.3.5":
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.17.12.")
        if not snapshot["result_set_complete"]:
            raise CapabilityError(
                "LIBRARY_SPACE_RESULTS_PAGINATED",
                "The browser did not verify every HKUL availability result page.",
                {"page_number": snapshot["page_number"], "page_count": snapshot["page_count"], "diagnostics": diagnostics},
            )
        if diagnostics["incomplete_available_slot_candidate_count"]:
            raise CapabilityError(
                "LIBRARY_SPACE_PARSE_INCOMPLETE",
                "One or more visible available HKUL time slots could not be parsed safely.",
                {"diagnostics": diagnostics},
            )
        if diagnostics["unclassified_status_cell_count"] or (
            diagnostics["facility_row_count"] > 0
            and diagnostics["status_cell_count"] == 0
        ):
            raise CapabilityError(
                "LIBRARY_SPACE_STATUS_PARSE_INCOMPLETE",
                "One or more visible HKUL availability cells could not be classified as available or booked.",
                {"diagnostics": diagnostics},
            )
        if not diagnostics["availability_marker_found"]:
            raise CapabilityError("LIBRARY_SPACE_PAGE_NOT_READY", "The verified HKUL availability page is not ready.")
        if not diagnostics["selected_filters_found"] or not diagnostics["table_matrix_found"]:
            raise CapabilityError("LIBRARY_SPACE_FILTERS_NOT_READY", "The exact HKUL availability filters or result matrix are not ready.")
        if (
            diagnostics["slot_candidate_count"] == 0
            and not diagnostics["verified_empty_result_found"]
        ):
            raise CapabilityError(
                "LIBRARY_SPACE_EMPTY_STATE_UNVERIFIED",
                "The HKUL matrix exposed no classifiable availability cells and no explicit empty-result message.",
                {"diagnostics": diagnostics},
            )
        return {
            "read_only": True,
            "systems_contacted": ["hkul_booking"],
            "navigation_interactions_performed": navigation["navigation_interactions_performed"],
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "library_writes_performed": 0,
            "booking_writes_performed": 0,
            "slot_selection_performed": False,
            "booking_form_opened": False,
            "facility_type": validated_input.facility_type,
            "location": snapshot["location"],
            "booking_facility_type": snapshot["booking_facility_type"],
            "date": snapshot["date"],
            "source_last_updated_at": snapshot["source_last_updated_at"],
            "result_set_complete": snapshot["result_set_complete"],
            "result_pages_read": navigation["result_pages_read"],
            "page_navigation_interactions_performed": navigation["page_navigation_interactions_performed"],
            "available_slot_count": snapshot["available_slot_count"],
            "available_slots": snapshot["available_slots"],
            "diagnostics": diagnostics,
            "navigation": {key: value for key, value in navigation.items() if key != "snapshot"},
        }


class LibrarySpaceBookingPreviewCapability(BaseCapability):
    input_model = LibrarySpaceBookingPreviewRequest
    manifest = CapabilityManifest(
        id="library.spaces.booking_preview",
        version=1,
        agent="library",
        title="Preview an exact HKUL space booking",
        description=(
            "Re-read one supported HKUL Book a Space availability page, match one exact "
            "facility/date/time target, and return a short-lived policy and eligibility "
            "preview. It never selects a slot, opens a booking form, or submits a reservation."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_authenticated_read_only",
        input_schema="LibrarySpaceBookingPreviewRequest",
        output_schema="LibrarySpaceBookingPreviewResult",
        timeout_seconds=35,
    )

    POLICY_VERIFIED_ON = "2026-09-24"
    POLICY_SOURCES = [
        {
            "title": "HKUL Book A Space",
            "url": "https://lib.hku.hk/general/e-form/book-a-space.html",
        },
        {
            "title": "HKUL Booking Policy",
            "url": "https://lib.hku.hk/general/e-form/L3_booking_policy.html",
        },
        {
            "title": "HKUL Main Library Level 3",
            "url": "https://lib.hku.hk/level3/zones.html",
        },
    ]

    def __init__(
        self,
        connector: BrowserSISConnector,
        preview_registry: LibraryBookingPreviewRegistry | None = None,
    ):
        self.connector = connector
        self.preview_registry = preview_registry or LibraryBookingPreviewRegistry()

    @staticmethod
    def _canonical_digest(value: dict) -> str:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_label(value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split()).casefold()

    @staticmethod
    def _slot_duration_minutes(slot: dict) -> int:
        start = datetime.strptime(slot["start_time"], "%H:%M")
        end = datetime.strptime(slot["end_time"], "%H:%M")
        return int((end - start).total_seconds() // 60)

    @classmethod
    def _facility(cls, facility_type: str) -> dict:
        return next(
            facility
            for facility in LibraryFacilityListCapability.FACILITIES
            if facility["facility_type"] == facility_type
        )

    def persisted_input(self, validated_input: LibrarySpaceBookingPreviewRequest) -> dict:
        return {
            "facility_type": validated_input.facility_type,
            "private_booking_target_persisted": False,
            "eligibility_category_persisted": False,
        }

    def persisted_result(self, result: dict) -> dict:
        return {
            "read_only": True,
            "ready": result.get("ready", False),
            "reason": result.get("reason"),
            "facility_type": result.get("facility_type"),
            "booking_writes_performed": 0,
            "private_preview_details_persisted": False,
        }

    async def execute(
        self,
        validated_input: LibrarySpaceBookingPreviewRequest,
        context: ExecutionContext,
    ) -> dict:
        require_supported_booking_date(validated_input.date)
        facility = self._facility(validated_input.facility_type)
        policy_contract = {
            "facility_type": facility["facility_type"],
            "name": facility["name"],
            "location": facility["location"],
            "booking_location": facility["booking_location"],
            "booking_facility_type": facility["booking_facility_type"],
            "capacity": facility["capacity"],
            "equipment": facility["equipment"],
            "eligible_categories": facility["eligibility"],
            "booking_policy": facility["booking_policy"],
            "policy_verified_on": self.POLICY_VERIFIED_ON,
            "policy_sources": self.POLICY_SOURCES,
        }
        policy_digest = self._canonical_digest(policy_contract)
        eligibility_supported = (
            validated_input.eligibility_category in facility["eligibility"]
        )
        target = {
            "facility_type": validated_input.facility_type,
            "location": facility["booking_location"],
            "booking_facility_type": facility["booking_facility_type"],
            "date": validated_input.date.isoformat(),
            "floor": validated_input.floor,
            "room": validated_input.room,
            "start_time": validated_input.start_time,
            "end_time": validated_input.end_time,
        }
        common = {
            "read_only": True,
            "domain_writes_performed": 0,
            "library_writes_performed": 0,
            "booking_writes_performed": 0,
            "slot_selection_performed": False,
            "booking_form_opened": False,
            "facility_type": validated_input.facility_type,
            "target": target,
            "eligibility": {
                "category": validated_input.eligibility_category,
                "supported_by_published_policy": eligibility_supported,
                "basis": "user_supplied_not_account_verified",
            },
            "policy": policy_contract,
            "policy_digest": policy_digest,
            "policy_acceptance_recorded": False,
        }
        if not eligibility_supported:
            return {
                **common,
                "ready": False,
                "reason": "eligibility_not_supported",
                "systems_contacted": [],
                "navigation_interactions_performed": False,
                "data_reads_performed": 0,
                "availability_observed_at": None,
                "preview": None,
                "preview_digest": None,
                "preview_expires_at": None,
                "warnings": [
                    "The supplied eligibility category is not listed for this facility in the verified HKUL policy."
                ],
            }

        try:
            navigation = await self.connector.search_library_space_availability(
                {
                    "facility_type": validated_input.facility_type,
                    "date": validated_input.date.isoformat(),
                }
            )
        except BrowserBridgeError as exc:
            raise _translate_browser_error(exc) from exc
        snapshot = navigation["snapshot"]
        diagnostics = snapshot["diagnostics"]
        if diagnostics["parser_version"] != "0.3.5":
            raise CapabilityError(
                "EXTENSION_UPDATE_REQUIRED",
                "Reload HKU AGENTS Browser Bridge 0.17.12.",
            )
        if not snapshot["result_set_complete"]:
            raise CapabilityError(
                "LIBRARY_SPACE_RESULTS_PAGINATED",
                "The browser did not verify every HKUL availability result page for this preview.",
                {"page_number": snapshot["page_number"], "page_count": snapshot["page_count"], "diagnostics": diagnostics},
            )
        if diagnostics["incomplete_available_slot_candidate_count"]:
            raise CapabilityError(
                "LIBRARY_SPACE_PARSE_INCOMPLETE",
                "One or more visible available HKUL time slots could not be parsed safely.",
                {"diagnostics": diagnostics},
            )
        if diagnostics["unclassified_status_cell_count"] or (
            diagnostics["facility_row_count"] > 0
            and diagnostics["status_cell_count"] == 0
        ):
            raise CapabilityError(
                "LIBRARY_SPACE_STATUS_PARSE_INCOMPLETE",
                "One or more visible HKUL availability cells could not be classified as available or booked.",
                {"diagnostics": diagnostics},
            )
        if not diagnostics["availability_marker_found"]:
            raise CapabilityError(
                "LIBRARY_SPACE_PAGE_NOT_READY",
                "The verified HKUL availability page is not ready.",
            )
        if not diagnostics["selected_filters_found"] or not diagnostics["table_matrix_found"]:
            raise CapabilityError(
                "LIBRARY_SPACE_FILTERS_NOT_READY",
                "The exact HKUL availability filters or result matrix are not ready.",
            )
        if (
            diagnostics["slot_candidate_count"] == 0
            and not diagnostics["verified_empty_result_found"]
        ):
            raise CapabilityError(
                "LIBRARY_SPACE_EMPTY_STATE_UNVERIFIED",
                "The HKUL matrix exposed no classifiable availability cells and no explicit empty-result message.",
                {"diagnostics": diagnostics},
            )

        observed_at = utc_now()
        observed_date = snapshot.get("date")
        source_last_updated_at = snapshot.get("source_last_updated_at")
        matched = []
        context_matches = (
            snapshot.get("location") == facility["booking_location"]
            and snapshot.get("booking_facility_type") == facility["booking_facility_type"]
        )
        if observed_date == validated_input.date.isoformat() and context_matches:
            requested_floor = self._normalize_label(validated_input.floor)
            requested_room = self._normalize_label(validated_input.room)
            for slot in snapshot["available_slots"]:
                floor_matches = (
                    requested_floor is None
                    or self._normalize_label(slot.get("floor")) == requested_floor
                )
                if (
                    floor_matches
                    and self._normalize_label(slot.get("room")) == requested_room
                    and slot["start_time"] == validated_input.start_time
                    and slot["end_time"] == validated_input.end_time
                ):
                    matched.append(slot)
        if len(matched) > 1:
            raise CapabilityError(
                "LIBRARY_SPACE_SLOT_AMBIGUOUS",
                "The requested booking target matched more than one visible available slot.",
                {"match_count": len(matched)},
            )

        navigation_summary = {
            key: value for key, value in navigation.items() if key != "snapshot"
        }
        if not context_matches:
            return {
                **common,
                "ready": False,
                "reason": "facility_context_mismatch",
                "systems_contacted": ["hkul_booking"],
                "navigation_interactions_performed": navigation["navigation_interactions_performed"],
                "data_reads_performed": 1,
                "availability_observed_at": observed_at.isoformat(),
                "source_last_updated_at": source_last_updated_at,
                "observed_date": observed_date,
                "preview": None,
                "preview_digest": None,
                "preview_expires_at": None,
                "diagnostics": diagnostics,
                "warnings": ["The live Location or Facility Type did not match the requested allowlisted target."],
                "navigation": navigation_summary,
            }
        if observed_date != validated_input.date.isoformat():
            return {
                **common,
                "ready": False,
                "reason": "date_mismatch",
                "systems_contacted": ["hkul_booking"],
                "navigation_interactions_performed": navigation[
                    "navigation_interactions_performed"
                ],
                "data_reads_performed": 1,
                "availability_observed_at": observed_at.isoformat(),
                "source_last_updated_at": source_last_updated_at,
                "observed_date": observed_date,
                "preview": None,
                "preview_digest": None,
                "preview_expires_at": None,
                "diagnostics": diagnostics,
                "warnings": [
                    "The live availability page displayed a different or unverifiable date; no booking preview was issued."
                ],
                "navigation": navigation_summary,
            }
        if not matched:
            return {
                **common,
                "ready": False,
                "reason": "slot_not_available",
                "systems_contacted": ["hkul_booking"],
                "navigation_interactions_performed": navigation[
                    "navigation_interactions_performed"
                ],
                "data_reads_performed": 1,
                "availability_observed_at": observed_at.isoformat(),
                "source_last_updated_at": source_last_updated_at,
                "observed_date": observed_date,
                "preview": None,
                "preview_digest": None,
                "preview_expires_at": None,
                "diagnostics": diagnostics,
                "warnings": [
                    "The exact requested slot was not present in the freshly read available-slot set."
                ],
                "navigation": navigation_summary,
            }

        required_duration = facility["booking_policy"].get("session_duration_minutes")
        observed_duration = self._slot_duration_minutes(matched[0])
        if required_duration is not None and observed_duration != required_duration:
            return {
                **common,
                "ready": False,
                "reason": "published_session_duration_mismatch",
                "systems_contacted": ["hkul_booking"],
                "navigation_interactions_performed": navigation[
                    "navigation_interactions_performed"
                ],
                "data_reads_performed": 1,
                "availability_observed_at": observed_at.isoformat(),
                "source_last_updated_at": source_last_updated_at,
                "observed_date": observed_date,
                "observed_slot_duration_minutes": observed_duration,
                "published_session_duration_minutes": required_duration,
                "preview": None,
                "preview_digest": None,
                "preview_expires_at": None,
                "diagnostics": diagnostics,
                "warnings": [
                    "The exact live availability interval conflicts with the published session duration; no preview was issued."
                ],
                "navigation": navigation_summary,
            }

        exact_target = {
            **target,
            "floor": matched[0].get("floor"),
            "room": matched[0].get("room"),
            "result_page_number": matched[0].get("page_number", 1),
            "status": "available",
        }
        if not exact_target["floor"]:
            return {
                **common,
                "ready": False,
                "reason": "floor_unverifiable",
                "systems_contacted": ["hkul_booking"],
                "navigation_interactions_performed": navigation["navigation_interactions_performed"],
                "data_reads_performed": 1,
                "availability_observed_at": observed_at.isoformat(),
                "source_last_updated_at": source_last_updated_at,
                "observed_date": observed_date,
                "preview": None,
                "preview_digest": None,
                "preview_expires_at": None,
                "diagnostics": diagnostics,
                "warnings": ["The live availability row did not expose a verifiable floor; no booking preview was issued."],
                "navigation": navigation_summary,
            }
        ttl_seconds = max(
            30,
            min(config.LIBRARY_BOOKING_PREVIEW_TTL_SECONDS, 300),
        )
        expires_at = observed_at + timedelta(seconds=ttl_seconds)
        preview = {
            "capability": self.manifest.id,
            "capability_version": self.manifest.version,
            "target": exact_target,
            "availability_observed_at": observed_at.isoformat(),
            "source_last_updated_at": source_last_updated_at,
            "expires_at": expires_at.isoformat(),
            "eligibility_category": validated_input.eligibility_category,
            "eligibility_basis": "user_supplied_not_account_verified",
            "policy_digest": policy_digest,
            "policy_verified_on": self.POLICY_VERIFIED_ON,
            "domain_write_authorized": False,
        }
        preview_digest = self._canonical_digest(preview)
        self.preview_registry.issue(preview_digest, preview)
        return {
            **common,
            "ready": True,
            "reason": "exact_slot_available",
            "systems_contacted": ["hkul_booking"],
            "navigation_interactions_performed": navigation[
                "navigation_interactions_performed"
            ],
            "data_reads_performed": 1,
            "availability_observed_at": observed_at.isoformat(),
            "source_last_updated_at": source_last_updated_at,
            "observed_date": observed_date,
            "preview": preview,
            "preview_digest": preview_digest,
            "preview_valid_for_seconds": ttl_seconds,
            "preview_expires_at": expires_at.isoformat(),
            "diagnostics": diagnostics,
            "warnings": [
                "Eligibility is checked only against the published category list and is not verified from Library account data.",
                "This preview is read-only, expires quickly, and does not authorize or perform a booking.",
            ] + ([
                "Discussion-room daily limits, the interleaving rule, and the minimum group size cannot be verified from the availability matrix or this preview; check them before booking."
            ] if validated_input.facility_type == "discussion_room" else []),
            "navigation": navigation_summary,
        }


class LibrarySpaceBookCapability(BaseCapability):
    """Supervised one-shot reservation behind two-phase user confirmation."""

    input_model = LibrarySpaceBookRequest
    manifest = CapabilityManifest(
        id="library.spaces.book",
        version=1,
        agent="library",
        title="Book one exact HKUL space",
        description=(
            "Re-read one exact slot, open and verify its HKUL booking form, then "
            "dispatch exactly one Submit after explicit policy and facility-rule acknowledgments and "
            "one-time two-phase confirmation. Verify the exact reservation in My Booking Record."
        ),
        mode=CapabilityMode.WRITE,
        risk=RiskLevel.HIGH,
        confirmation=ConfirmationMode.EXPLICIT_TWO_PHASE,
        required_connections=["sis_browser"],
        availability=(
            "supervised_one_shot_confirmation"
            if config.LIBRARY_BOOKING_WRITES_ENABLED and library_booking_host_is_loopback()
            else "disabled_pending_operator_enablement"
        ),
        input_schema="LibrarySpaceBookRequest",
        output_schema="LibrarySpaceBookResult",
        timeout_seconds=180,
    )

    def __init__(
        self,
        connector: BrowserSISConnector,
        preview_registry: LibraryBookingPreviewRegistry,
    ):
        self.connector = connector
        self.preview_registry = preview_registry

    def preview(self, validated_input: LibrarySpaceBookRequest) -> dict:
        if not library_booking_host_is_loopback():
            raise PolicyDeniedError(
                "LIBRARY_BOOKING_LOCAL_ONLY",
                "HKUL booking is available only when HKU AGENTS is bound to a loopback host and used through the local GUI.",
            )
        issued = self.preview_registry.require(validated_input.preview_digest)
        target = issued.get("target") or {}
        facility_type = target.get("facility_type")
        expected_route = SUPERVISED_BOOKING_ROUTES.get(facility_type)
        if (facility_type not in SUPERVISED_BOOKING_FACILITY_TYPES
                or not expected_route
                or (target.get("location"), target.get("booking_facility_type")) != expected_route):
            raise CapabilityError(
                "LIBRARY_BOOKING_FACILITY_NOT_ENABLED",
                "F2 live submission is limited to policy-verified Main Library single study rooms and discussion rooms.",
            )
        if facility_type == "discussion_room" and validated_input.discussion_room_rules_acknowledged is not True:
            raise CapabilityError(
                "LIBRARY_DISCUSSION_ROOM_RULES_ACK_REQUIRED",
                "Discussion-room booking requires an explicit user attestation for the minimum group size, daily booking limits, and interleaving rule.",
            )
        return {
            "capability": self.manifest.id,
            "capability_version": self.manifest.version,
            "mode": self.manifest.mode.value,
            "risk": self.manifest.risk.value,
            "preview_digest": validated_input.preview_digest,
            "exact_target": issued["target"],
            "eligibility_category": issued["eligibility_category"],
            "eligibility_basis": issued["eligibility_basis"],
            "policy_digest": issued["policy_digest"],
            "policy_verified_on": issued["policy_verified_on"],
            "availability_observed_at": issued["availability_observed_at"],
            "preview_expires_at": issued["expires_at"],
            "effect": "Submit exactly one HKUL facility booking and accept the displayed HKUL policy.",
            "discussion_room_rules_acknowledged": validated_input.discussion_room_rules_acknowledged is True,
            "discussion_room_rules_attestation": (
                "I confirm at least two patrons will use the room, and my bookings for that day will comply with the two-session/120-minute limit and the published interleaving rule."
                if facility_type == "discussion_room" else None
            ),
            "external_submission_enabled": config.LIBRARY_BOOKING_WRITES_ENABLED,
            "policy_acceptance_acknowledged": validated_input.policy_acceptance_acknowledged,
        }

    def persisted_input(self, validated_input: LibrarySpaceBookRequest) -> dict:
        return {
            "preview_digest": validated_input.preview_digest,
            "policy_acceptance_acknowledged": True,
            "discussion_room_rules_acknowledged": validated_input.discussion_room_rules_acknowledged is True,
            "exact_target_bound": True,
        }

    def persisted_preview(self, preview: dict) -> dict:
        """Keep exact room/date/time targets out of persistent action-draft storage."""
        return {
            "capability": preview.get("capability"),
            "capability_version": preview.get("capability_version"),
            "mode": preview.get("mode"),
            "risk": preview.get("risk"),
            "preview_digest": preview.get("preview_digest"),
            "eligibility_basis": preview.get("eligibility_basis"),
            "policy_digest": preview.get("policy_digest"),
            "policy_verified_on": preview.get("policy_verified_on"),
            "preview_expires_at": preview.get("preview_expires_at"),
            "external_submission_enabled": preview.get("external_submission_enabled"),
            "policy_acceptance_acknowledged": preview.get("policy_acceptance_acknowledged"),
            "discussion_room_rules_acknowledged": preview.get("discussion_room_rules_acknowledged", False),
            "exact_target_persisted": False,
        }

    def persisted_result(self, result: dict) -> dict:
        return {
            "booking_writes_performed": result.get("booking_writes_performed", 0),
            "submit_clicks_dispatched": result.get("submit_clicks_dispatched", 0),
            "discussion_room_rules_acknowledged": result.get("discussion_room_rules_acknowledged", False),
            "outcome": result.get("outcome"),
            "exact_target_verified_in_booking_record": result.get("exact_target_verified_in_booking_record", False),
            "record_match_count": result.get("record_match_count", 0),
            "private_target_persisted": False,
        }

    async def execute(
        self,
        validated_input: LibrarySpaceBookRequest,
        context: ExecutionContext,
    ) -> dict:
        # Re-check preview/process provenance after confirmation. Preparation
        # performs the last read-only availability check and form comparison.
        issued = self.preview_registry.require(validated_input.preview_digest)
        if not library_booking_host_is_loopback():
            raise PolicyDeniedError(
                "LIBRARY_BOOKING_LOCAL_ONLY",
                "HKUL booking is available only when HKU AGENTS is bound to a loopback host and used through the local GUI.",
                {"booking_writes_performed": 0, "preview_consumed": False},
            )
        if not config.LIBRARY_BOOKING_WRITES_ENABLED:
            raise PolicyDeniedError(
                "LIBRARY_BOOKING_WRITE_DISABLED",
                "HKUL booking submission is disabled pending supervised F2 live-write acceptance.",
                {
                    "booking_writes_performed": 0,
                    "preview_consumed": False,
                    "recovery": "Set LIBRARY_BOOKING_WRITES_ENABLED=true only for a supervised low-impact test after reviewing the exact action preview.",
                },
            )
        target = issued.get("target") or {}
        facility_type = target.get("facility_type")
        expected_route = SUPERVISED_BOOKING_ROUTES.get(facility_type)
        if (facility_type not in SUPERVISED_BOOKING_FACILITY_TYPES
                or not expected_route
                or (target.get("location"), target.get("booking_facility_type")) != expected_route):
            raise CapabilityError(
                "LIBRARY_BOOKING_FACILITY_NOT_ENABLED",
                "F2 live submission is limited to policy-verified Main Library single study rooms and discussion rooms.",
                {"booking_writes_performed": 0, "preview_consumed": False},
            )
        if (facility_type == "discussion_room"
                and validated_input.discussion_room_rules_acknowledged is not True):
            raise CapabilityError(
                "LIBRARY_DISCUSSION_ROOM_RULES_ACK_REQUIRED",
                "Discussion-room booking requires a fresh explicit user attestation before execution.",
                {"booking_writes_performed": 0, "preview_consumed": False},
            )
        if target.get("result_page_number") is None:
            raise CapabilityError("LIBRARY_BOOKING_PAGE_UNVERIFIABLE", "The exact availability result page is not verifiable.")
        try:
            prepared = await self.connector.prepare_library_space_booking(
                {
                    "facility_type": target["facility_type"],
                    "target": target,
                    "discussion_room_rules_acknowledged": validated_input.discussion_room_rules_acknowledged is True,
                }
            )
        except BrowserBridgeError as exc:
            if exc.code == "BROWSER_TIMEOUT":
                raise CapabilityError(
                    "LIBRARY_BOOKING_PREPARE_TIMEOUT",
                    "Read-only slot and booking-form preparation timed out. No Submit command was issued; let the browser settle, then start a fresh availability and confirmation flow.",
                    {
                        "booking_writes_performed": 0,
                        "submit_clicks_dispatched": 0,
                        "slot_selection_performed": "unknown",
                        "booking_form_opened": "unknown",
                        "preview_consumed": False,
                    },
                ) from exc
            raise _translate_browser_error(exc) from exc
        if (prepared.get("ready_to_submit") is not True
                or prepared.get("exact_target_verified") is not True
                or prepared.get("booking_writes_performed") != 0):
            raise CapabilityError(
                "LIBRARY_BOOKING_FORM_MISMATCH",
                "The refreshed slot or exact live booking form did not match the confirmed preview; no Submit was issued.",
                {"booking_writes_performed": 0, "slot_selection_performed": prepared.get("slot_selection_performed", False)},
            )

        # Consume the process-issued preview immediately before the one-shot
        # Submit command. Any uncertain response is terminal and never retried.
        self.preview_registry.consume(validated_input.preview_digest, context.task_id)
        try:
            result = await self.connector.submit_library_space_booking(
                {
                    "target": target,
                    "execution_id": context.task_id,
                    "prepared_tab_id": prepared.get("prepared_tab_id"),
                    "policy_acceptance_acknowledged": True,
                    "discussion_room_rules_acknowledged": validated_input.discussion_room_rules_acknowledged is True,
                }
            )
        except BrowserBridgeError as exc:
            # A disconnect can happen after the extension received the
            # one-shot command; treat transport loss as ambiguous, not zero writes.
            if exc.code in {"PAIRING_TOKEN_REJECTED", "COMMAND_NOT_ALLOWED", "LIBRARY_BOOKING_CONFIRM_HANDLER_UNAVAILABLE", "LIBRARY_BOOKING_CONFIRMATION_MISMATCH", "LIBRARY_BOOKING_FORM_MISMATCH", "LIBRARY_BOOKING_SUBMIT_AMBIGUOUS", "LIBRARY_BOOKING_FORM_NOT_READY"}:
                raise CapabilityError(
                    exc.code,
                    str(exc),
                    {"booking_writes_performed": 0, "submit_clicks_dispatched": 0, "preview_consumed": True},
                ) from exc
            raise ExecutionUnknownError(
                "LIBRARY_BOOKING_OUTCOME_UNKNOWN",
                "The one-shot Submit may have reached HKUL, but no authoritative result was received. Inspect My Booking Record manually; do not retry.",
                {"booking_writes_performed": "unknown", "submit_clicks_dispatched": "unknown", "preview_consumed": True},
            ) from exc
        except Exception as exc:
            # The browser may already have dispatched Submit before a schema,
            # transport, or response-processing error surfaced. Never retry.
            raise ExecutionUnknownError(
                "LIBRARY_BOOKING_OUTCOME_UNKNOWN",
                "The one-shot Submit may have reached HKUL, but its response could not be verified. Inspect My Booking Record manually; do not retry.",
                {"booking_writes_performed": "unknown", "submit_clicks_dispatched": "unknown", "preview_consumed": True},
            ) from exc
        if (result.get("outcome") != "confirmed"
                or result.get("booking_writes_performed") != 1
                or result.get("submit_clicks_dispatched") != 1
                or result.get("exact_target_verified_in_booking_record") is not True
                or result.get("record_match_count") != 1):
            raise ExecutionUnknownError(
                "LIBRARY_BOOKING_OUTCOME_UNKNOWN",
                "Submit was dispatched, but the exact booking was not verified exactly once. Inspect My Booking Record manually; do not retry.",
                {"booking_writes_performed": result.get("booking_writes_performed", "unknown"), "submit_clicks_dispatched": result.get("submit_clicks_dispatched", "unknown"), "record_match_count": result.get("record_match_count", 0)},
            )
        return {
            **result,
            "discussion_room_rules_acknowledged": (
                validated_input.discussion_room_rules_acknowledged is True
            ),
        }
