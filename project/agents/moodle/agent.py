from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field

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
from services.moodle import MoodleAssignmentService, MoodleCourseService


class MoodleDashboardInspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoodleCourseListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoodleUpcomingAssignmentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_ahead: int = Field(default=14, ge=1, le=90)


def _supported_parser(value: object, minimum: tuple[int, int, int]) -> bool:
    try:
        return tuple(int(part) for part in str(value).split(".")) >= minimum
    except (TypeError, ValueError):
        return False


def _navigation_performed(steps: list[str]) -> bool:
    return any(
        step in {
            "portal_to_moodle",
            "moodle_portal_sso_started",
            "moodle_fixed_route_to_dashboard",
        }
        for step in steps
    )


def _navigation_security(navigation: dict) -> dict:
    return {
        "portal_session_reused": bool(navigation.get("portal_session_reused")),
        "moodle_session_reused": bool(navigation.get("moodle_session_reused")),
        "sso_interactions_performed": bool(
            navigation.get("sso_interactions_performed")
        ),
        "credentials_entered": False,
        "mfa_interactions_performed": False,
    }


def _systems_contacted(navigation: dict) -> list[str]:
    return (
        ["moodle"]
        if navigation.get("source_origin") == "https://moodle.hku.hk"
        else ["portal", "moodle"]
    )


class MoodleDashboardInspectCapability(BaseCapability):
    input_model = MoodleDashboardInspectRequest
    manifest = CapabilityManifest(
        id="moodle.dashboard.inspect",
        version=1,
        agent="moodle",
        title="Inspect HKU Moodle Dashboard",
        description=(
            "Navigate from an authenticated HKU Portal tab to Moodle and return only "
            "login state and dashboard diagnostics. Course and assignment data are not read."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_read_only_diagnostics",
        input_schema="MoodleDashboardInspectRequest",
        output_schema="MoodleDashboardInspectResult",
        timeout_seconds=42,
    )

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

    async def execute(
        self, validated_input: MoodleDashboardInspectRequest, context: ExecutionContext
    ) -> dict:
        try:
            binding = await self.connector.bind_hku_tab()
            navigation = await self.connector.open_moodle()
        except BrowserBridgeError as exc:
            if exc.code in {"COMMAND_NOT_ALLOWED", "PAGE_SCRIPT_UNAVAILABLE"}:
                raise CapabilityError(
                    "EXTENSION_UPDATE_REQUIRED",
                    "Reload HKU AGENTS Browser Bridge 0.15.2 and refresh HKU Portal and Moodle.",
                ) from exc
            raise CapabilityError(exc.code, str(exc)) from exc
        snapshot = navigation["snapshot"]
        diagnostics = snapshot.get("diagnostics") or {}
        if snapshot.get("logged_in") is not True or snapshot.get("page_kind") != "dashboard":
            raise CapabilityError(
                "MOODLE_DASHBOARD_NOT_READY",
                "The verified Moodle Dashboard is not ready for inspection.",
                {"page_kind": snapshot.get("page_kind"), "diagnostics": diagnostics},
            )
        if not _supported_parser(diagnostics.get("parser_version"), (0, 4, 1)):
            raise CapabilityError(
                "EXTENSION_UPDATE_REQUIRED",
                "Reload HKU AGENTS Browser Bridge 0.15.2 before Moodle inspection.",
            )
        steps = navigation.get("steps", [])
        return {
            "read_only": True,
            "systems_contacted": _systems_contacted(navigation),
            "navigation_interactions_performed": _navigation_performed(steps),
            **_navigation_security(navigation),
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "moodle_writes_performed": 0,
            "course_data_read": False,
            "assignment_data_read": False,
            "binding": {
                "origin": binding.get("origin"),
                "page_kind": binding.get("page_kind"),
                "logged_in": binding.get("logged_in"),
            },
            "navigation": {
                key: value for key, value in navigation.items() if key != "snapshot"
            },
            "dashboard": {
                "origin": snapshot.get("origin"),
                "logged_in": snapshot.get("logged_in"),
                "page_kind": snapshot.get("page_kind"),
                "diagnostics": diagnostics,
            },
        }


class MoodleCourseListCapability(BaseCapability):
    input_model = MoodleCourseListRequest
    manifest = CapabilityManifest(
        id="moodle.courses.list",
        version=1,
        agent="moodle",
        title="List visible HKU Moodle courses",
        description=(
            "Navigate to the authenticated Moodle Dashboard and return only visible "
            "course membership identifiers and names. It does not read assignments, "
            "grades, participants, messages, or submissions."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_read_only_private_memory",
        input_schema="MoodleCourseListRequest",
        output_schema="MoodleCourseListResult",
        timeout_seconds=42,
    )

    def __init__(
        self, connector: BrowserSISConnector, courses: MoodleCourseService
    ) -> None:
        self.connector = connector
        self.courses = courses

    def persisted_result(self, result: dict) -> dict:
        course_list = result.get("course_list") or {}
        return {
            "read_only": True,
            "domain_writes_performed": 0,
            "moodle_writes_performed": 0,
            "course_count": course_list.get("course_count", 0),
            "source_fetched_at": course_list.get("fetched_at"),
            "private_course_details_persisted": False,
        }

    async def execute(
        self, validated_input: MoodleCourseListRequest, context: ExecutionContext
    ) -> dict:
        try:
            binding = await self.connector.bind_hku_tab()
            navigation = await self.connector.open_moodle()
            snapshot = await self.connector.list_moodle_courses()
        except BrowserBridgeError as exc:
            if exc.code in {"COMMAND_NOT_ALLOWED", "PAGE_SCRIPT_UNAVAILABLE"}:
                raise CapabilityError(
                    "EXTENSION_UPDATE_REQUIRED",
                    "Reload HKU AGENTS Browser Bridge 0.15.2 and refresh HKU Portal and Moodle.",
                ) from exc
            raise CapabilityError(exc.code, str(exc)) from exc

        diagnostics = snapshot.get("diagnostics") or {}
        if not _supported_parser(diagnostics.get("parser_version"), (0, 4, 1)):
            raise CapabilityError(
                "EXTENSION_UPDATE_REQUIRED",
                "Reload HKU AGENTS Browser Bridge 0.15.2 before listing Moodle courses.",
            )
        unparsed = int(diagnostics.get("unparsed_course_candidate_count", 0))
        if unparsed:
            raise CapabilityError(
                "MOODLE_COURSE_PARSE_INCOMPLETE",
                "One or more visible Moodle course candidates could not be parsed safely.",
                {"diagnostics": diagnostics},
            )

        course_list = self.courses.update(
            snapshot.get("courses", []),
            {
                "kind": "moodle_dashboard_visible_courses",
                "origin": snapshot.get("origin"),
                "page_kind": snapshot.get("page_kind"),
                "parser_version": diagnostics.get("parser_version"),
                "visibility_scope": "dashboard_dom",
            },
        )
        steps = navigation.get("steps", [])
        candidate_count = int(diagnostics.get("course_candidate_count", 0))
        warnings = list(course_list.get("normalization_warnings", []))
        if candidate_count == 0:
            warnings.append(
                "No course candidates were exposed in the current Dashboard DOM; "
                "an empty result does not prove that the account has no Moodle courses."
            )
        return {
            "read_only": True,
            "systems_contacted": _systems_contacted(navigation),
            "navigation_interactions_performed": _navigation_performed(steps),
            **_navigation_security(navigation),
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "moodle_writes_performed": 0,
            "course_membership_read": True,
            "assignment_data_read": False,
            "grade_data_read": False,
            "participant_data_read": False,
            "submission_data_read": False,
            "binding": {
                "origin": binding.get("origin"),
                "page_kind": binding.get("page_kind"),
                "logged_in": binding.get("logged_in"),
            },
            "navigation": {
                key: value for key, value in navigation.items() if key != "snapshot"
            },
            "course_list": course_list,
            "diagnostics": diagnostics,
            "warnings": warnings,
        }


class MoodleUpcomingAssignmentsCapability(BaseCapability):
    input_model = MoodleUpcomingAssignmentsRequest
    manifest = CapabilityManifest(
        id="moodle.assignments.upcoming",
        version=1,
        agent="moodle",
        title="List upcoming HKU Moodle assignments",
        description=(
            "Read machine-dated assignment and activity deadlines visible on the "
            "authenticated Moodle Dashboard for a bounded future window. It does not "
            "open course activities or read grades, participants, or submissions."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_read_only_private_memory",
        input_schema="MoodleUpcomingAssignmentsRequest",
        output_schema="MoodleUpcomingAssignmentsResult",
        timeout_seconds=42,
    )

    def __init__(
        self, connector: BrowserSISConnector, assignments: MoodleAssignmentService
    ) -> None:
        self.connector = connector
        self.assignments = assignments

    def persisted_result(self, result: dict) -> dict:
        assignment_list = result.get("assignment_list") or {}
        return {
            "read_only": True,
            "domain_writes_performed": 0,
            "moodle_writes_performed": 0,
            "days_ahead": result.get("window", {}).get("days_ahead"),
            "assignment_count": assignment_list.get("assignment_count", 0),
            "source_fetched_at": assignment_list.get("fetched_at"),
            "private_assignment_details_persisted": False,
        }

    async def execute(
        self, validated_input: MoodleUpcomingAssignmentsRequest, context: ExecutionContext
    ) -> dict:
        try:
            binding = await self.connector.bind_hku_tab()
            navigation = await self.connector.open_moodle()
            snapshot = await self.connector.list_moodle_upcoming_assignments()
        except BrowserBridgeError as exc:
            if exc.code in {"COMMAND_NOT_ALLOWED", "PAGE_SCRIPT_UNAVAILABLE"}:
                raise CapabilityError(
                    "EXTENSION_UPDATE_REQUIRED",
                    "Reload HKU AGENTS Browser Bridge 0.15.2 and refresh HKU Portal and Moodle.",
                ) from exc
            raise CapabilityError(exc.code, str(exc)) from exc

        diagnostics = snapshot.get("diagnostics") or {}
        if not _supported_parser(diagnostics.get("parser_version"), (0, 4, 1)):
            raise CapabilityError(
                "EXTENSION_UPDATE_REQUIRED",
                "Reload HKU AGENTS Browser Bridge 0.15.2 before reading Moodle assignments.",
            )
        if int(diagnostics.get("unparsed_assignment_candidate_count", 0)):
            raise CapabilityError(
                "MOODLE_ASSIGNMENT_PARSE_INCOMPLETE",
                "One or more visible Moodle assignment candidates could not be parsed safely.",
                {"diagnostics": diagnostics},
            )

        now = datetime.now(timezone.utc)
        ends_at = now + timedelta(days=validated_input.days_ahead)
        visible = []
        overdue_count = 0
        beyond_window_count = 0
        for item in snapshot.get("assignments", []):
            due_at = datetime.fromisoformat(str(item["due_at"]).replace("Z", "+00:00"))
            if due_at < now:
                overdue_count += 1
            elif due_at > ends_at:
                beyond_window_count += 1
            else:
                visible.append(item)

        assignment_list = self.assignments.update(
            visible,
            {
                "kind": "moodle_dashboard_visible_deadlines",
                "origin": snapshot.get("origin"),
                "page_kind": snapshot.get("page_kind"),
                "parser_version": diagnostics.get("parser_version"),
                "visibility_scope": "dashboard_dom",
                "window": {
                    "as_of": now.isoformat(),
                    "days_ahead": validated_input.days_ahead,
                    "ends_at": ends_at.isoformat(),
                },
            },
        )
        warnings = []
        if int(diagnostics.get("parsed_assignment_display_date_count", 0)):
            warnings.append(
                "One or more deadlines were normalized from strict English Moodle "
                "display text using the Asia/Hong_Kong timezone; inspect due_at_source."
            )
        if int(diagnostics.get("inferred_assignment_year_count", 0)):
            warnings.append(
                "One or more displayed deadlines omitted the year; the parser selected "
                "the nearest plausible Asia/Hong_Kong year. Inspect due_at_source."
            )
        if int(diagnostics.get("assignment_candidate_count", 0)) == 0:
            warnings.append(
                "No assignment candidates were exposed in the current Dashboard DOM; "
                "an empty result does not prove there are no Moodle deadlines."
            )
        steps = navigation.get("steps", [])
        return {
            "read_only": True,
            "systems_contacted": _systems_contacted(navigation),
            "navigation_interactions_performed": _navigation_performed(steps),
            **_navigation_security(navigation),
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "moodle_writes_performed": 0,
            "assignment_data_read": True,
            "grade_data_read": False,
            "participant_data_read": False,
            "submission_data_read": False,
            "activity_pages_opened": 0,
            "window": {
                "as_of": now.isoformat(),
                "days_ahead": validated_input.days_ahead,
                "ends_at": ends_at.isoformat(),
            },
            "binding": {
                "origin": binding.get("origin"),
                "page_kind": binding.get("page_kind"),
                "logged_in": binding.get("logged_in"),
            },
            "navigation": {
                key: value for key, value in navigation.items() if key != "snapshot"
            },
            "assignment_list": assignment_list,
            "excluded": {
                "overdue_count": overdue_count,
                "beyond_window_count": beyond_window_count,
            },
            "diagnostics": diagnostics,
            "warnings": warnings,
        }
