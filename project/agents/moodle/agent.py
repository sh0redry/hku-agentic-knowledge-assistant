from __future__ import annotations

from pydantic import BaseModel, ConfigDict

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


class MoodleDashboardInspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
                    "Reload HKU AGENTS Browser Bridge 0.9.1 and refresh HKU Portal and Moodle.",
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
        if diagnostics.get("parser_version") != "0.1.0":
            raise CapabilityError(
                "EXTENSION_UPDATE_REQUIRED",
                "Reload HKU AGENTS Browser Bridge 0.9.1 before Moodle inspection.",
            )
        steps = navigation.get("steps", [])
        return {
            "read_only": True,
            "systems_contacted": ["portal", "moodle"]
            if binding.get("origin") != "https://moodle.hku.hk"
            else ["moodle"],
            "navigation_interactions_performed": any(
                step in {"portal_to_moodle", "moodle_fixed_route_to_dashboard"}
                for step in steps
            ),
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
