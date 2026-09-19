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


def _translate_browser_error(exc: BrowserBridgeError) -> CapabilityError:
    if exc.code in {"COMMAND_NOT_ALLOWED", "PAGE_SCRIPT_UNAVAILABLE"}:
        return CapabilityError(
            "EXTENSION_UPDATE_REQUIRED",
            "Reload HKU AGENTS Browser Bridge 0.14.2 before using HKUL tools.",
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
        if diagnostics["parser_version"] != "0.1.2":
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.14.2.")
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
        if diagnostics["parser_version"] != "0.1.2":
            raise CapabilityError("EXTENSION_UPDATE_REQUIRED", "Reload HKU AGENTS Browser Bridge 0.14.2.")
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
