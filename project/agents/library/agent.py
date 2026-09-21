from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.base import BaseCapability
from agents.errors import CapabilityError
from agents.models import CapabilityManifest, CapabilityMode, ConfirmationMode, ExecutionContext, RiskLevel
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
        "single_study_room", "studio_editing_room", "study_table"
    ]


class LibraryFacilityListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LibraryResearchRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")


def _translate_browser_error(exc: BrowserBridgeError) -> CapabilityError:
    if exc.code in {"COMMAND_NOT_ALLOWED", "PAGE_SCRIPT_UNAVAILABLE"}:
        return CapabilityError(
            "EXTENSION_UPDATE_REQUIRED",
            "Reload HKU AGENTS Browser Bridge 0.15.2 before using HKUL tools.",
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
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.15.2.")
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
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.15.2.")
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
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.15.2.")
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
            "policy_verified_on": "2026-09-19",
            "policy_sources": [
                {"title": "HKUL Book A Space", "url": "https://lib.hku.hk/general/e-form/book-a-space.html"},
                {"title": "HKUL Booking Policy", "url": "https://lib.hku.hk/general/e-form/L3_booking_policy.html"},
            ],
            "warnings": [
                "Facility availability and booking policies can change; re-check the cited official policy before acting.",
                "Listing a facility does not establish current eligibility or availability and does not authorize a booking.",
            ],
        }


class LibrarySpaceAvailabilityCapability(BaseCapability):
    input_model = LibrarySpaceAvailabilityRequest
    manifest = CapabilityManifest(
        id="library.spaces.search_availability",
        version=1,
        agent="library",
        title="Read HKUL space availability",
        description=(
            "Open one of three fixed HKUL Book a Space facility routes and read visible "
            "available time slots after the user completes HKUL authentication. It never "
            "selects a slot, enters booking details, or submits a reservation."
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
        if diagnostics["parser_version"] != "0.2.2":
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.15.2.")
        if diagnostics["incomplete_available_slot_candidate_count"]:
            raise CapabilityError(
                "LIBRARY_SPACE_PARSE_INCOMPLETE",
                "One or more visible available HKUL time slots could not be parsed safely.",
                {"diagnostics": diagnostics},
            )
        if not diagnostics["availability_marker_found"]:
            raise CapabilityError("LIBRARY_SPACE_PAGE_NOT_READY", "The verified HKUL availability page is not ready.")
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
            "date": snapshot["date"],
            "available_slot_count": snapshot["available_slot_count"],
            "available_slots": snapshot["available_slots"],
            "diagnostics": diagnostics,
            "navigation": {key: value for key, value in navigation.items() if key != "snapshot"},
        }
