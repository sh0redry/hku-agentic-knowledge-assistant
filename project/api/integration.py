from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from agents.models import TaskStatus
from api.schemas import IntegrationResponse, IntegrationTaskSummary
from browser_bridge.service import BrowserBridgeError
from connectors.sis.models import SISLivePreflightRequest, SISNavigationRequest


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
