from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agents.models import TaskStatus
from agents.briefing.agent import DailyBriefingRequest
from agents.moodle.agent import (
    MoodleCourseListRequest,
    MoodleDashboardInspectRequest,
    MoodleUpcomingAssignmentsRequest,
)
from agents.portal.agent import PortalNoticeListRequest
from agents.library.agent import (
    LibraryFacilityListRequest,
    LibraryHoursAndLocationsRequest,
    LibraryResearchRecordRequest,
    LibraryResearchSearchRequest,
    LibrarySpaceAvailabilityRequest,
    LibrarySpaceBookingPreviewRequest,
)
from api.schemas import IntegrationResponse, IntegrationTaskSummary
from browser_bridge.service import BrowserBridgeError
from connectors.sis.models import (
    SISExamStatusRequest,
    SISFreeSlotsRequest,
    SISLivePreflightRequest,
    SISNavigationRequest,
    SISNextClassRequest,
    SISTimetableConflictRequest,
    SISTimetableSyncRequest,
)


class IntegrationAPIError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        recovery: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.recovery = recovery


def _task_summary(record) -> IntegrationTaskSummary:
    return IntegrationTaskSummary(
        id=record.id,
        capability=record.capability,
        status=record.status.value,
        phase=record.phase,
        correlation_id=record.correlation_id,
        error=record.error,
    )


def create_integration_router(expected_token: str) -> APIRouter:
    if len(expected_token) < 32:
        raise ValueError("INTEGRATION_API_TOKEN must contain at least 32 characters.")

    router = APIRouter(prefix="/api/v1/integration", tags=["integration"])
    bearer = HTTPBearer(auto_error=False)

    async def authorize(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> str:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise IntegrationAPIError(
                401,
                "AUTH_REQUIRED",
                "A local Integration API bearer token is required.",
                "Configure the host adapter with INTEGRATION_API_TOKEN.",
            )
        if not hmac.compare_digest(credentials.credentials, expected_token):
            raise IntegrationAPIError(
                403,
                "AUTH_INVALID",
                "The local Integration API bearer token is invalid.",
                "Copy the current token from the local GUI or configure the same environment token.",
            )
        return request.state.correlation_id

    def response(
        correlation_id: str,
        *,
        ok: bool,
        result: dict[str, Any] | None = None,
        task=None,
        error: dict[str, Any] | None = None,
    ) -> IntegrationResponse:
        return IntegrationResponse(
            ok=ok,
            correlation_id=correlation_id,
            result=result,
            task=_task_summary(task) if task is not None else None,
            error=error,
        )

    def browser_recovery(error_code: str, fallback: str) -> str:
        if error_code == "PAIRING_TOKEN_REJECTED":
            return (
                "Copy the current Browser Pairing Token from the HKU AGENTS Connections "
                "tab into the extension popup, then select Save and connect."
            )
        if error_code in {"BROWSER_NOT_CONNECTED", "BROWSER_DISCONNECTED"}:
            return (
                "Open the extension popup to inspect its connection state or select "
                "Reconnect now."
            )
        if error_code == "SIS_SSO_FAILED":
            return (
                "Do not sign in on the PeopleSoft error page. Close that failed SIS tab, "
                "refresh the authenticated HKU Portal tab, bind it again, and retry once. "
                "If Portal asks for login or MFA, complete it manually."
            )
        if error_code in {"TIMETABLE_LOGIN_REQUIRED", "TIMETABLE_NAVIGATION_TIMEOUT"}:
            return (
                "Refresh the authenticated HKU Portal tab and retry My Weekly Schedule. "
                "Complete any visible HKU CAS login or MFA manually."
            )
        return fallback

    @router.get("/status", response_model=IntegrationResponse)
    async def integration_status(request: Request, correlation_id: str = Depends(authorize)):
        container = request.app.state.container
        manifests = [item.model_dump(mode="json") for item in container.registry.manifests()]
        return response(
            correlation_id,
            ok=True,
            result={
                "service": "hku-agents",
                "service_version": request.app.version,
                "mode": "local-first",
                "auth_mode": "bearer",
                "capabilities": manifests,
                "connections": container.connection_status(),
            },
        )

    @router.post("/sis/sync", response_model=IntegrationResponse)
    async def sync_sis_course_lists(
        request: Request, correlation_id: str = Depends(authorize)
    ):
        try:
            snapshot = await request.app.state.container.connectors[
                "sis_browser"
            ].inspect_cart()
        except BrowserBridgeError as exc:
            status = 504 if exc.code == "BROWSER_TIMEOUT" else 409
            raise IntegrationAPIError(
                status,
                exc.code,
                str(exc),
                browser_recovery(
                    exc.code,
                    "Bind the SIS tab and open Enrollment Add Classes, then retry.",
                ),
            ) from exc
        return response(correlation_id, ok=True, result=snapshot)

    async def run_timetable_task(
        request: Request,
        correlation_id: str,
        capability_id: str,
        body,
    ) -> IntegrationResponse:
        record = await request.app.state.container.tasks.submit_and_wait(
            capability_id,
            body.model_dump(mode="json"),
            correlation_id=correlation_id,
        )
        if record.status != TaskStatus.COMPLETED:
            task_error = record.error or {
                "code": "TASK_FAILED",
                "message": "The read-only timetable task did not complete.",
            }
            error_code = task_error.get("code", "TASK_FAILED")
            recovery = (
                "Synchronize the requested My Weekly Schedule term before running local timetable calculations."
                if error_code in {"TIMETABLE_NOT_SYNCED", "TIMETABLE_TERM_MISMATCH"}
                else "Keep My Weekly Schedule open and report the task diagnostics so its live term marker can be added safely."
                if error_code == "TIMETABLE_TERM_UNDETERMINED"
                else "Reload the unpacked HKU AGENTS Browser Bridge extension, then retry."
                if error_code == "EXTENSION_UPDATE_REQUIRED"
                else browser_recovery(
                    error_code,
                    "Check the bound SIS page and browser connection, then retry.",
                )
            )
            return response(
                correlation_id,
                ok=False,
                task=record,
                error={
                    "code": error_code,
                    "message": task_error.get("message", "The timetable task failed."),
                    "recovery": recovery,
                },
            )
        return response(correlation_id, ok=True, task=record, result=record.result)

    async def run_moodle_task(
        request: Request,
        correlation_id: str,
        capability_id: str,
        body: (
            MoodleDashboardInspectRequest
            | MoodleCourseListRequest
            | MoodleUpcomingAssignmentsRequest
        ),
    ) -> IntegrationResponse:
        record = await request.app.state.container.tasks.submit_and_wait(
            capability_id,
            body.model_dump(mode="json"),
            correlation_id=correlation_id,
        )
        if record.status != TaskStatus.COMPLETED:
            task_error = record.error or {
                "code": "TASK_FAILED",
                "message": "The read-only Moodle inspection did not complete.",
            }
            error_code = task_error.get("code", "TASK_FAILED")
            recovery = (
                "Reload the unpacked HKU AGENTS Browser Bridge 0.17.5, then refresh HKU Portal and Moodle."
                if error_code == "EXTENSION_UPDATE_REQUIRED"
                else "Open HKU Portal and complete login/MFA, then retry the Moodle tool."
                if error_code == "MOODLE_LOGIN_REQUIRED"
                else "Complete the visible password, MFA, CAPTCHA, consent, or recovery prompt in Chrome, then retry."
                if error_code == "SSO_MANUAL_ACTION_REQUIRED"
                else "Keep the authenticated Moodle Dashboard open and report the count-only parser diagnostics."
                if error_code == "MOODLE_COURSE_PARSE_INCOMPLETE"
                else "Keep the authenticated Moodle Dashboard open and report the assignment parser diagnostics."
                if error_code == "MOODLE_ASSIGNMENT_PARSE_INCOMPLETE"
                else browser_recovery(
                    error_code,
                    "Keep the authenticated HKU Portal tab active and retry Moodle Dashboard inspection.",
                )
            )
            return response(
                correlation_id,
                ok=False,
                task=record,
                error={
                    "code": error_code,
                    "message": task_error.get("message", "The Moodle task failed."),
                    "recovery": recovery,
                },
            )
        return response(correlation_id, ok=True, task=record, result=record.result)

    @router.post("/moodle/dashboard/inspect", response_model=IntegrationResponse)
    async def inspect_moodle_dashboard(
        request: Request,
        body: MoodleDashboardInspectRequest | None = None,
        correlation_id: str = Depends(authorize),
    ):
        return await run_moodle_task(
            request,
            correlation_id,
            "moodle.dashboard.inspect",
            body or MoodleDashboardInspectRequest(),
        )

    @router.post("/moodle/courses/list", response_model=IntegrationResponse)
    async def list_moodle_courses(
        request: Request,
        body: MoodleCourseListRequest | None = None,
        correlation_id: str = Depends(authorize),
    ):
        return await run_moodle_task(
            request,
            correlation_id,
            "moodle.courses.list",
            body or MoodleCourseListRequest(),
        )

    @router.post("/moodle/assignments/upcoming", response_model=IntegrationResponse)
    async def list_upcoming_moodle_assignments(
        body: MoodleUpcomingAssignmentsRequest,
        request: Request,
        correlation_id: str = Depends(authorize),
    ):
        return await run_moodle_task(
            request,
            correlation_id,
            "moodle.assignments.upcoming",
            body,
        )

    async def run_library_task(request: Request, correlation_id: str, capability_id: str, body) -> IntegrationResponse:
        record = await request.app.state.container.tasks.submit_and_wait(
            capability_id, body.model_dump(mode="json"), correlation_id=correlation_id
        )
        if record.status != TaskStatus.COMPLETED:
            task_error = record.error or {"code": "TASK_FAILED", "message": "The read-only HKUL task did not complete."}
            error_code = task_error.get("code", "TASK_FAILED")
            recovery = (
                "Reload HKU AGENTS Browser Bridge 0.17.5, then retry."
                if error_code == "EXTENSION_UPDATE_REQUIRED"
                else "Complete HKUL authentication in the visible Chrome tab, then retry; credentials and MFA remain manual."
                if error_code == "LIBRARY_LOGIN_REQUIRED"
                else "Use today's or tomorrow's date in Asia/Hong_Kong, then retry; the live HKUL date dropdown is authoritative."
                if error_code == "LIBRARY_SPACE_DATE_OUT_OF_WINDOW"
                else "The result exceeded the supported page limit or a page was not completely read; report page_count and count-only parser diagnostics."
                if error_code == "LIBRARY_SPACE_RESULTS_PAGINATED"
                else "Keep the relevant Find@HKUL results or full-display page open and retry; if it persists, report the count-only parser diagnostics."
                if error_code in {
                    "LIBRARY_RESEARCH_PARSE_INCOMPLETE",
                    "LIBRARY_SEARCH_NOT_READY",
                    "LIBRARY_ITEM_NOT_READY",
                    "LIBRARY_ITEM_PARSE_INCOMPLETE",
                    "LIBRARY_ACCESS_PARSE_INCOMPLETE",
                    "LIBRARY_HOURS_NOT_READY",
                    "LIBRARY_HOURS_PARSE_INCOMPLETE",
                }
                else "Open the Browser Bridge popup, restore the local connection, and retry."
                if error_code in {
                    "BROWSER_NOT_CONNECTED",
                    "BROWSER_DISCONNECTED",
                    "BROWSER_TIMEOUT",
                    "PAIRING_TOKEN_REJECTED",
                }
                else "Keep the HKUL Book a Space availability page open and report the count-only parser diagnostics."
            )
            return response(correlation_id, ok=False, task=record, error={
                "code": error_code,
                "message": task_error.get("message", "The HKUL task failed."),
                "recovery": recovery,
            })
        return response(correlation_id, ok=True, task=record, result=record.result)

    @router.post("/library/research/search", response_model=IntegrationResponse)
    async def search_library_research(
        body: LibraryResearchSearchRequest,
        request: Request,
        correlation_id: str = Depends(authorize),
    ):
        return await run_library_task(request, correlation_id, "library.research.search", body)

    @router.post("/library/spaces/search-availability", response_model=IntegrationResponse)
    async def search_library_space_availability(
        body: LibrarySpaceAvailabilityRequest,
        request: Request,
        correlation_id: str = Depends(authorize),
    ):
        return await run_library_task(request, correlation_id, "library.spaces.search_availability", body)

    @router.post("/library/spaces/booking-preview", response_model=IntegrationResponse)
    async def preview_library_space_booking(
        body: LibrarySpaceBookingPreviewRequest,
        request: Request,
        correlation_id: str = Depends(authorize),
    ):
        return await run_library_task(
            request,
            correlation_id,
            "library.spaces.booking_preview",
            body,
        )

    @router.post("/library/spaces/list-facilities", response_model=IntegrationResponse)
    async def list_library_facilities(
        request: Request,
        body: LibraryFacilityListRequest | None = None,
        correlation_id: str = Depends(authorize),
    ):
        return await run_library_task(
            request,
            correlation_id,
            "library.spaces.list_facilities",
            body or LibraryFacilityListRequest(),
        )

    @router.post("/library/hours-and-locations", response_model=IntegrationResponse)
    async def read_library_hours_and_locations(
        request: Request,
        body: LibraryHoursAndLocationsRequest | None = None,
        correlation_id: str = Depends(authorize),
    ):
        return await run_library_task(
            request,
            correlation_id,
            "library.hours_and_locations",
            body or LibraryHoursAndLocationsRequest(),
        )

    @router.post("/library/research/item", response_model=IntegrationResponse)
    async def read_library_research_item(
        body: LibraryResearchRecordRequest,
        request: Request,
        correlation_id: str = Depends(authorize),
    ):
        return await run_library_task(request, correlation_id, "library.research.item", body)

    @router.post("/library/research/access-options", response_model=IntegrationResponse)
    async def read_library_research_access_options(
        body: LibraryResearchRecordRequest,
        request: Request,
        correlation_id: str = Depends(authorize),
    ):
        return await run_library_task(
            request, correlation_id, "library.research.access_options", body
        )

    @router.post("/briefing/today", response_model=IntegrationResponse)
    async def daily_briefing(
        request: Request,
        body: DailyBriefingRequest | None = None,
        correlation_id: str = Depends(authorize),
    ):
        record = await request.app.state.container.tasks.submit_and_wait(
            "briefing.today",
            (body or DailyBriefingRequest()).model_dump(mode="json"),
            correlation_id=correlation_id,
        )
        if record.status != TaskStatus.COMPLETED:
            task_error = record.error or {
                "code": "TASK_FAILED",
                "message": "The local daily briefing task did not complete.",
            }
            return response(
                correlation_id,
                ok=False,
                task=record,
                error={
                    "code": task_error.get("code", "TASK_FAILED"),
                    "message": task_error.get(
                        "message", "The local daily briefing task failed."
                    ),
                    "recovery": (
                        "Synchronize the weekly timetable, Moodle upcoming assignments, "
                        "and Portal notices, "
                        "then retry without restarting HKU AGENTS."
                    ),
                },
            )
        return response(correlation_id, ok=True, task=record, result=record.result)

    @router.post("/portal/notices/list", response_model=IntegrationResponse)
    async def list_portal_notices(
        request: Request,
        body: PortalNoticeListRequest | None = None,
        correlation_id: str = Depends(authorize),
    ):
        record = await request.app.state.container.tasks.submit_and_wait(
            "portal.notices.list",
            (body or PortalNoticeListRequest()).model_dump(mode="json"),
            correlation_id=correlation_id,
        )
        if record.status != TaskStatus.COMPLETED:
            task_error = record.error or {
                "code": "TASK_FAILED",
                "message": "The Portal notice task did not complete.",
            }
            error_code = task_error.get("code", "TASK_FAILED")
            recovery = (
                "Reload HKU AGENTS Browser Bridge 0.17.5 and refresh HKU Portal."
                if error_code == "EXTENSION_UPDATE_REQUIRED"
                else "Keep the authenticated HKU Portal home page open and report the count-only parser diagnostics."
                if error_code == "PORTAL_NOTICE_PARSE_INCOMPLETE"
                else "Open HKU Portal, complete login/MFA, and retry."
            )
            return response(
                correlation_id,
                ok=False,
                task=record,
                error={
                    "code": error_code,
                    "message": task_error.get("message", "The Portal notice task failed."),
                    "recovery": recovery,
                },
            )
        return response(correlation_id, ok=True, task=record, result=record.result)

    @router.post("/sis/timetable/sync-weekly", response_model=IntegrationResponse)
    async def sync_weekly_timetable(
        body: SISTimetableSyncRequest,
        request: Request,
        correlation_id: str = Depends(authorize),
    ):
        return await run_timetable_task(
            request, correlation_id, "sis.timetable.sync_weekly", body
        )

    @router.post("/sis/timetable/next-class", response_model=IntegrationResponse)
    async def next_sis_class(
        request: Request,
        body: SISNextClassRequest | None = None,
        correlation_id: str = Depends(authorize),
    ):
        return await run_timetable_task(
            request,
            correlation_id,
            "sis.timetable.next_class",
            body or SISNextClassRequest(),
        )

    @router.post("/sis/timetable/free-slots", response_model=IntegrationResponse)
    async def find_sis_free_slots(
        request: Request,
        body: SISFreeSlotsRequest | None = None,
        correlation_id: str = Depends(authorize),
    ):
        return await run_timetable_task(
            request,
            correlation_id,
            "sis.timetable.find_free_slots",
            body or SISFreeSlotsRequest(),
        )

    @router.post("/sis/timetable/check-conflicts", response_model=IntegrationResponse)
    async def check_sis_timetable_conflicts(
        body: SISTimetableConflictRequest,
        request: Request,
        correlation_id: str = Depends(authorize),
    ):
        return await run_timetable_task(
            request, correlation_id, "sis.timetable.check_conflicts", body
        )

    @router.post("/sis/timetable/exam-status", response_model=IntegrationResponse)
    async def inspect_sis_exam_status(
        request: Request,
        body: SISExamStatusRequest | None = None,
        correlation_id: str = Depends(authorize),
    ):
        return await run_timetable_task(
            request,
            correlation_id,
            "sis.timetable.exam_status",
            body or SISExamStatusRequest(),
        )

    @router.post("/sis/navigate", response_model=IntegrationResponse)
    async def navigate_to_enrollment_add_classes(
        request: Request,
        body: SISNavigationRequest | None = None,
        correlation_id: str = Depends(authorize),
    ):
        record = await request.app.state.container.tasks.submit_and_wait(
            "sis.navigation.open_enrollment_add_classes",
            (body or SISNavigationRequest()).model_dump(mode="json"),
            correlation_id=correlation_id,
        )
        if record.status != TaskStatus.COMPLETED:
            task_error = record.error or {
                "code": "TASK_FAILED",
                "message": "Restricted SIS navigation did not complete.",
            }
            error_code = task_error.get("code", "TASK_FAILED")
            if error_code == "TERM_SELECTION_REQUIRED":
                recovery = "Provide one exact SIS term label, for example 2026-27 Sem 2."
            elif error_code in {"TERM_NOT_AVAILABLE", "TERM_MISMATCH"}:
                recovery = "Choose one of the term labels currently shown by SIS."
            else:
                recovery = browser_recovery(
                    error_code,
                    "Keep the authenticated HKU Portal tab active, reload the updated "
                    "extension, and retry. Login and MFA always remain manual.",
                )
            return response(
                correlation_id,
                ok=False,
                task=record,
                error={
                    "code": error_code,
                    "message": task_error.get("message", "Restricted SIS navigation failed."),
                    "recovery": recovery,
                },
            )
        return response(correlation_id, ok=True, task=record, result=record.result)

    @router.post("/sis/preflight", response_model=IntegrationResponse)
    async def integration_live_preflight(
        body: SISLivePreflightRequest,
        request: Request,
        correlation_id: str = Depends(authorize),
    ):
        record = await request.app.state.container.tasks.submit_and_wait(
            "sis.enrollment.live_preflight",
            body.model_dump(mode="json"),
            correlation_id=correlation_id,
        )
        if record.status != TaskStatus.COMPLETED:
            task_error = record.error or {
                "code": "TASK_FAILED",
                "message": "The live SIS preflight task did not complete.",
            }
            return response(
                correlation_id,
                ok=False,
                task=record,
                error={
                    "code": task_error.get("code", "TASK_FAILED"),
                    "message": task_error.get("message", "The live SIS preflight task failed."),
                    "recovery": browser_recovery(
                        task_error.get("code", "TASK_FAILED"),
                        "Check the SIS connection and page state, then retry.",
                    ),
                },
            )
        return response(
            correlation_id,
            ok=True,
            task=record,
            result=record.result,
        )

    @router.post("/sis/navigate-and-preflight", response_model=IntegrationResponse)
    async def navigate_and_preflight(
        body: SISLivePreflightRequest,
        request: Request,
        correlation_id: str = Depends(authorize),
    ):
        record = await request.app.state.container.tasks.submit_and_wait(
            "sis.enrollment.navigate_and_preflight",
            body.model_dump(mode="json"),
            correlation_id=correlation_id,
        )
        if record.status != TaskStatus.COMPLETED:
            task_error = record.error or {
                "code": "TASK_FAILED",
                "message": "Automatic SIS navigation and preflight did not complete.",
            }
            error_code = task_error.get("code", "TASK_FAILED")
            if error_code in {"TERM_NOT_AVAILABLE", "TERM_MISMATCH"}:
                recovery = "Choose one of the term labels currently shown by SIS."
            else:
                recovery = browser_recovery(
                    error_code,
                    "Keep the authenticated HKU Portal tab active, verify the extension "
                    "connection, and retry. Login and MFA always remain manual.",
                )
            return response(
                correlation_id,
                ok=False,
                task=record,
                error={
                    "code": error_code,
                    "message": task_error.get(
                        "message", "Automatic SIS navigation and preflight failed."
                    ),
                    "recovery": recovery,
                },
            )
        return response(correlation_id, ok=True, task=record, result=record.result)

    return router
