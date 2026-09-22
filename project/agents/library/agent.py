from __future__ import annotations

import hashlib
import json
from datetime import date as date_type, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import config
from agents.base import BaseCapability
from agents.errors import CapabilityError
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
        "single_study_room", "studio_editing_room", "study_table", "study_room"
    ]
    date: date_type


class LibrarySpaceBookingPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_type: Literal[
        "single_study_room", "studio_editing_room", "study_table", "study_room"
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
            "Reload HKU AGENTS Browser Bridge 0.17.1 before using HKUL tools.",
        )
    return CapabilityError(exc.code, str(exc))


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
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.17.1.")
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
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.17.1.")
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
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.17.1.")
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
            "booking_facility_type": "Studio and Editing Rooms",
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
    ]

    def persisted_result(self, result: dict) -> dict:
        return {
            "read_only": True,
            "facility_count": result.get("facility_count", 0),
            "policy_verified_on": result.get("policy_verified_on"),
            "domain_writes_performed": 0,
        }

    async def execute(self, validated_input: LibraryFacilityListRequest, context: ExecutionContext) -> dict:
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
            "catalog_scope": "availability_search_supported_facilities",
            "facilities": self.FACILITIES,
            "policy_verified_on": "2026-09-22",
            "policy_sources": [
                {"title": "HKUL Book A Space", "url": "https://lib.hku.hk/general/e-form/book-a-space.html"},
                {"title": "HKUL Booking Policy", "url": "https://lib.hku.hk/general/e-form/L3_booking_policy.html"},
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
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.17.1.")
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
        try:
            navigation = await self.connector.search_library_space_availability(
                validated_input.model_dump(mode="json")
            )
        except BrowserBridgeError as exc:
            raise _translate_browser_error(exc) from exc
        snapshot = navigation["snapshot"]
        diagnostics = snapshot["diagnostics"]
        if diagnostics["parser_version"] != "0.3.1":
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.17.1.")
        if diagnostics["incomplete_available_slot_candidate_count"]:
            raise CapabilityError(
                "LIBRARY_SPACE_PARSE_INCOMPLETE",
                "One or more visible available HKUL time slots could not be parsed safely.",
                {"diagnostics": diagnostics},
            )
        if not diagnostics["availability_marker_found"]:
            raise CapabilityError("LIBRARY_SPACE_PAGE_NOT_READY", "The verified HKUL availability page is not ready.")
        if not diagnostics["selected_filters_found"] or not diagnostics["table_matrix_found"]:
            raise CapabilityError("LIBRARY_SPACE_FILTERS_NOT_READY", "The exact HKUL availability filters or result matrix are not ready.")
        if not snapshot["result_set_complete"]:
            raise CapabilityError(
                "LIBRARY_SPACE_RESULTS_PAGINATED",
                "Availability spans multiple pages; F1.1 stops rather than treating the current page as complete.",
                {"page_number": snapshot["page_number"], "page_count": snapshot["page_count"]},
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

    POLICY_VERIFIED_ON = "2026-09-22"
    POLICY_SOURCES = [
        {
            "title": "HKUL Book A Space",
            "url": "https://lib.hku.hk/general/e-form/book-a-space.html",
        },
        {
            "title": "HKUL Booking Policy",
            "url": "https://lib.hku.hk/general/e-form/L3_booking_policy.html",
        },
    ]

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

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
        if diagnostics["parser_version"] != "0.3.1":
            raise CapabilityError(
                "EXTENSION_UPDATE_REQUIRED",
                "Reload HKU AGENTS Browser Bridge 0.17.1.",
            )
        if diagnostics["incomplete_available_slot_candidate_count"]:
            raise CapabilityError(
                "LIBRARY_SPACE_PARSE_INCOMPLETE",
                "One or more visible available HKUL time slots could not be parsed safely.",
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
        if not snapshot["result_set_complete"]:
            raise CapabilityError(
                "LIBRARY_SPACE_RESULTS_PAGINATED",
                "Availability spans multiple pages; the preview cannot prove the result set is complete.",
                {"page_number": snapshot["page_number"], "page_count": snapshot["page_count"]},
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

        exact_target = {
            **target,
            "floor": matched[0].get("floor"),
            "room": matched[0].get("room"),
            "status": "available",
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
            ],
            "navigation": navigation_summary,
        }
