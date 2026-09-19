from __future__ import annotations

from browser_bridge.models import (
    MoodleDashboardSnapshot,
    MoodleAssignmentListSnapshot,
    MoodleCourseListSnapshot,
    MoodleNavigationResult,
    LibraryResearchNavigationResult,
    LibrarySpaceNavigationResult,
    PortalPageSnapshot,
    PortalNoticeListSnapshot,
    SISNavigationResult,
    SISPageSnapshot,
    WeeklyTimetableNavigationResult,
    WeeklyTimetableSnapshot,
)
from browser_bridge.service import BrowserBridgeError, BrowserBridgeService
from connectors.base import BaseConnector
from connectors.sis.protocol import BrowserCommand, BrowserCommandName


class BrowserSISConnector(BaseConnector):
    """Deterministic read-only adapter for the paired local extension."""

    id = "sis_browser"

    def __init__(self, bridge: BrowserBridgeService):
        self.bridge = bridge

    def health(self) -> dict:
        return self.bridge.status()

    async def bind_hku_tab(self) -> dict:
        data = await self._command(BrowserCommandName.BIND_HKU_TAB)
        if data.get("origin") in {
            "https://hkuportal.hku.hk",
            "https://studentportal.hku.hk",
        }:
            return PortalPageSnapshot.model_validate(data).model_dump(mode="json")
        if data.get("origin") == "https://sweb.hku.hk":
            return WeeklyTimetableSnapshot.model_validate(data).model_dump(mode="json")
        if data.get("origin") == "https://moodle.hku.hk":
            return MoodleDashboardSnapshot.model_validate(data).model_dump(mode="json")
        return SISPageSnapshot.model_validate(data).model_dump(mode="json")

    async def inspect_portal(self) -> dict:
        data = await self._command(BrowserCommandName.INSPECT_PORTAL)
        return PortalPageSnapshot.model_validate(data).model_dump(mode="json")

    async def list_portal_notices(self) -> dict:
        data = await self._command(BrowserCommandName.LIST_PORTAL_NOTICES)
        return PortalNoticeListSnapshot.model_validate(data).model_dump(mode="json")

    async def open_sis(self) -> dict:
        data = await self._command(BrowserCommandName.OPEN_SIS)
        return SISPageSnapshot.model_validate(data).model_dump(mode="json")

    async def open_enrollment_add_classes(self, term_label: str | None = None) -> dict:
        payload = {} if term_label is None else {"term_label": term_label}
        data = await self._command(
            BrowserCommandName.OPEN_ENROLLMENT_ADD_CLASSES,
            payload=payload,
        )
        return SISNavigationResult.model_validate(data).model_dump(mode="json")

    async def open_weekly_timetable(self) -> dict:
        data = await self._command(BrowserCommandName.OPEN_WEEKLY_TIMETABLE)
        return WeeklyTimetableNavigationResult.model_validate(data).model_dump(mode="json")

    async def open_moodle(self) -> dict:
        data = await self._command(BrowserCommandName.OPEN_MOODLE)
        return MoodleNavigationResult.model_validate(data).model_dump(mode="json")

    async def inspect_moodle_dashboard(self) -> dict:
        data = await self._command(BrowserCommandName.INSPECT_MOODLE_DASHBOARD)
        return MoodleDashboardSnapshot.model_validate(data).model_dump(mode="json")

    async def list_moodle_courses(self) -> dict:
        data = await self._command(BrowserCommandName.LIST_MOODLE_COURSES)
        return MoodleCourseListSnapshot.model_validate(data).model_dump(mode="json")

    async def list_moodle_upcoming_assignments(self) -> dict:
        data = await self._command(BrowserCommandName.LIST_MOODLE_UPCOMING_ASSIGNMENTS)
        return MoodleAssignmentListSnapshot.model_validate(data).model_dump(mode="json")

    async def search_library_research(self, payload: dict) -> dict:
        data = await self._command(BrowserCommandName.SEARCH_LIBRARY_RESEARCH, payload)
        return LibraryResearchNavigationResult.model_validate(data).model_dump(mode="json")

    async def search_library_space_availability(self, payload: dict) -> dict:
        data = await self._command(
            BrowserCommandName.SEARCH_LIBRARY_SPACE_AVAILABILITY, payload
        )
        return LibrarySpaceNavigationResult.model_validate(data).model_dump(mode="json")

    async def bind_tab(self) -> dict:
        data = await self._command(BrowserCommandName.BIND_SIS_TAB)
        return SISPageSnapshot.model_validate(data).model_dump(mode="json")

    async def inspect_page(self) -> dict:
        data = await self._command(BrowserCommandName.INSPECT_PAGE)
        return SISPageSnapshot.model_validate(data).model_dump(mode="json")

    async def inspect_cart(self) -> dict:
        data = await self._command(BrowserCommandName.INSPECT_CART)
        return self._validate_cart(data)

    async def preflight_snapshot(self) -> dict:
        data = await self._command(BrowserCommandName.PREFLIGHT)
        return self._validate_cart(data)

    @staticmethod
    def _validate_cart(data: dict) -> dict:
        snapshot = SISPageSnapshot.model_validate(data)
        if snapshot.page_kind != "cart":
            raise BrowserBridgeError(
                "WRONG_SIS_PAGE", "Open the Temporary Course List before inspecting the cart."
            )
        return snapshot.model_dump(mode="json")

    async def _command(self, name: BrowserCommandName, payload: dict | None = None) -> dict:
        result = await self.bridge.request(
            BrowserCommand(command=name, payload=payload or {})
        )
        if not result.ok:
            error = result.error or {}
            raise BrowserBridgeError(
                str(error.get("code", "BROWSER_COMMAND_FAILED")),
                str(error.get("message", f"Browser command '{name.value}' failed.")),
            )
        return result.data
