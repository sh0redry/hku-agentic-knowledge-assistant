from __future__ import annotations

from datetime import datetime, timezone

from agents.base import BaseCapability
from agents.errors import CapabilityError
from agents.models import (
    CapabilityManifest,
    CapabilityMode,
    ConfirmationMode,
    ExecutionContext,
    RiskLevel,
)
from browser_bridge.service import BrowserBridgeError
from connectors.sis.browser import BrowserSISConnector
from connectors.sis.models import (
    SISExamStatusRequest,
    SISFreeSlotsRequest,
    SISNextClassRequest,
    SISTimetableConflictRequest,
    SISTimetableSyncRequest,
)
from services.timetable import TimetableService


def _manifest(
    capability_id: str,
    title: str,
    description: str,
    input_schema: str,
    output_schema: str,
    *,
    browser: bool = False,
) -> CapabilityManifest:
    return CapabilityManifest(
        id=capability_id,
        agent="timetable",
        title=title,
        description=description,
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM if browser else RiskLevel.LOW,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"] if browser else [],
        availability="local_browser_read_only" if browser else "process_cache_derived",
        input_schema=input_schema,
        output_schema=output_schema,
        timeout_seconds=42 if browser else 5,
    )


class PrivateTimetableCapability(BaseCapability):
    """Keep private timetable rows in memory, not in the SQLite task history."""

    def persisted_input(self, validated_input) -> dict:
        data = validated_input.model_dump(mode="json")
        meetings = data.pop("candidate_meetings", None)
        if meetings is not None:
            data["candidate_meeting_count"] = len(meetings)
        return data

    def persisted_result(self, result: dict) -> dict:
        timetable = result.get("timetable") or {}
        return {
            "read_only": True,
            "domain_writes_performed": result.get("domain_writes_performed", 0),
            "term_label": result.get("term_label") or timetable.get("term_label"),
            "meeting_count": timetable.get("meeting_count"),
            "publication_state": result.get("publication_state"),
            "private_details_persisted": False,
        }


class SISTimetableSyncCapability(PrivateTimetableCapability):
    input_model = SISTimetableSyncRequest
    manifest = _manifest(
        "sis.timetable.sync_weekly",
        "Synchronize HKU My Weekly Schedule",
        "Navigate to the dedicated read-only HKU My Weekly Schedule application and synchronize class meetings for one exact term.",
        "SISTimetableSyncRequest",
        "SISTimetableSnapshot",
        browser=True,
    )

    def __init__(self, connector: BrowserSISConnector, timetable: TimetableService):
        self.connector = connector
        self.timetable = timetable

    async def execute(
        self, validated_input: SISTimetableSyncRequest, context: ExecutionContext
    ) -> dict:
        try:
            binding = await self.connector.bind_hku_tab()
            navigation = await self.connector.open_weekly_timetable()
        except BrowserBridgeError as exc:
            if exc.code in {"COMMAND_NOT_ALLOWED", "PAGE_SCRIPT_UNAVAILABLE"}:
                raise CapabilityError(
                    "EXTENSION_UPDATE_REQUIRED",
                    "Reload HKU AGENTS Browser Bridge 0.8.2 and refresh the HKU Portal and My Weekly Schedule tabs.",
                ) from exc
            raise CapabilityError(exc.code, str(exc)) from exc
        snapshot = navigation["snapshot"]
        if not snapshot.get("term_label"):
            raise CapabilityError(
                "TIMETABLE_TERM_UNDETERMINED",
                "The My Weekly Schedule term could not be verified from either an explicit label or its displayed week.",
                {
                    "page_kind": snapshot.get("page_kind"),
                    "diagnostics": snapshot.get("diagnostics") or {},
                },
            )
        if snapshot.get("term_label") != validated_input.term_label:
            raise CapabilityError(
                "TIMETABLE_TERM_MISMATCH",
                "The live My Weekly Schedule term does not match the requested term.",
                {
                    "requested_term_label": validated_input.term_label,
                    "term_label": snapshot.get("term_label"),
                },
            )
        diagnostics = snapshot.get("diagnostics") or {}
        parser_version = diagnostics.get("parser_version")
        try:
            parser_supported = tuple(
                int(part) for part in parser_version.split(".")
            ) >= (0, 2, 1)
        except (AttributeError, ValueError):
            parser_supported = False
        if not parser_supported:
            raise CapabilityError(
                "EXTENSION_UPDATE_REQUIRED",
                "Reload HKU AGENTS Browser Bridge 0.8.2 or newer before timetable synchronization.",
            )
        if not diagnostics.get("timetable_marker_found"):
            raise CapabilityError(
                "TIMETABLE_MARKER_NOT_FOUND",
                "The HKU My Weekly Schedule page could not be verified.",
                {"diagnostics": diagnostics},
            )
        if int(diagnostics.get("unparsed_candidate_count", 0)) > 0:
            raise CapabilityError(
                "TIMETABLE_PARSE_INCOMPLETE",
                "One or more My Weekly Schedule entries could not be parsed safely.",
                {"diagnostics": diagnostics},
            )
        navigation_steps = navigation.get("steps", [])
        cache = self.timetable.update(
            validated_input.term_label,
            snapshot.get("meetings", []),
            {
                "kind": "hku_weekly_timetable",
                "origin": snapshot.get("origin"),
                "page_kind": snapshot.get("page_kind"),
                "parser_version": parser_version,
                "authoritative_for": "weekly_schedule",
                "week_range": snapshot.get("week_range"),
            },
        )
        return {
            "read_only": True,
            "simulated": False,
            "systems_contacted": ["portal", "timetable"]
            if binding.get("origin") != "https://sweb.hku.hk"
            else ["timetable"],
            "navigation_interactions_performed": "portal_to_weekly_timetable"
            in navigation_steps,
            "term_selection_performed": False,
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "schedule_writes_performed": 0,
            "binding": {
                "origin": binding.get("origin"),
                "page_kind": binding.get("page_kind"),
                "logged_in": binding.get("logged_in"),
            },
            "navigation": {
                key: value for key, value in navigation.items() if key != "snapshot"
            },
            "timetable": cache,
        }


class SISNextClassCapability(PrivateTimetableCapability):
    input_model = SISNextClassRequest
    manifest = _manifest(
        "sis.timetable.next_class",
        "Find Next SIS Class",
        "Derive the next scheduled class from the process-local synchronized timetable without browser interaction.",
        "SISNextClassRequest",
        "SISNextClassResult",
    )

    def __init__(self, timetable: TimetableService):
        self.timetable = timetable

    async def execute(
        self, validated_input: SISNextClassRequest, context: ExecutionContext
    ) -> dict:
        return self.timetable.next_class(
            term_label=validated_input.term_label,
            as_of=validated_input.as_of,
            days_ahead=validated_input.days_ahead,
        )


class SISFreeSlotsCapability(PrivateTimetableCapability):
    input_model = SISFreeSlotsRequest
    manifest = _manifest(
        "sis.timetable.find_free_slots",
        "Find Free Timetable Slots",
        "Calculate weekly free periods from the process-local synchronized timetable without browser interaction.",
        "SISFreeSlotsRequest",
        "SISFreeSlotsResult",
    )

    def __init__(self, timetable: TimetableService):
        self.timetable = timetable

    async def execute(
        self, validated_input: SISFreeSlotsRequest, context: ExecutionContext
    ) -> dict:
        return self.timetable.free_slots(
            term_label=validated_input.term_label,
            weekdays=validated_input.weekdays,
            window_start=validated_input.window_start,
            window_end=validated_input.window_end,
            minimum_minutes=validated_input.minimum_minutes,
        )


class SISTimetableConflictCapability(PrivateTimetableCapability):
    input_model = SISTimetableConflictRequest
    manifest = _manifest(
        "sis.timetable.check_conflicts",
        "Check Timetable Conflicts",
        "Compare candidate meetings with the process-local synchronized timetable without browser interaction.",
        "SISTimetableConflictRequest",
        "SISTimetableConflictResult",
    )

    def __init__(self, timetable: TimetableService):
        self.timetable = timetable

    async def execute(
        self, validated_input: SISTimetableConflictRequest, context: ExecutionContext
    ) -> dict:
        return self.timetable.conflicts(
            term_label=validated_input.term_label,
            candidates=[
                item.model_dump(mode="json")
                for item in validated_input.candidate_meetings
            ],
        )


class SISExamStatusCapability(PrivateTimetableCapability):
    input_model = SISExamStatusRequest
    manifest = _manifest(
        "sis.timetable.exam_status",
        "Inspect SIS Examination Timetable Status",
        "Inspect an already-open bound SIS Examination Timetables page and report publication state and visible entries.",
        "SISExamStatusRequest",
        "SISExamStatusResult",
        browser=True,
    )

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

    async def execute(
        self, validated_input: SISExamStatusRequest, context: ExecutionContext
    ) -> dict:
        try:
            snapshot = await self.connector.inspect_page()
        except BrowserBridgeError as exc:
            raise CapabilityError(exc.code, str(exc)) from exc
        requested = validated_input.term_label
        observed = snapshot.get("term_label")
        state = snapshot.get("exam_publication_state", "unavailable")
        issues = []
        parser_version = (snapshot.get("diagnostics") or {}).get("parser_version")
        try:
            parser_supported = tuple(
                int(part) for part in parser_version.split(".")
            ) >= (0, 3, 0)
        except (AttributeError, ValueError):
            parser_supported = False
        if not parser_supported:
            raise CapabilityError(
                "EXTENSION_UPDATE_REQUIRED",
                "Reload HKU AGENTS Browser Bridge 0.7.0 or newer before exam inspection.",
            )
        if snapshot.get("page_kind") != "exam_schedule":
            issues.append(
                "Open and bind the SIS Examination Timetables page before inspection."
            )
            state = "unavailable"
        if requested and observed and requested != observed:
            issues.append(
                "The visible examination timetable term does not match the requested term."
            )
        if requested and not observed:
            issues.append("The examination timetable term could not be determined.")
        return {
            "ok": not issues,
            "read_only": True,
            "simulated": False,
            "browser_interactions_performed": False,
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "requested_term_label": requested,
            "term_label": observed,
            "publication_state": state,
            "exam_entries": snapshot.get("exam_entries", []),
            "issues": issues,
            "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": {
                "kind": "live_sis_page",
                "origin": snapshot.get("origin"),
                "page_kind": snapshot.get("page_kind"),
                "parser_version": parser_version,
            },
        }
