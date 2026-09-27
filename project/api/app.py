from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agents.errors import CapabilityError
from agents.library.agent import library_booking_host_is_loopback
from agents.models import TERMINAL_TASK_STATUSES, TaskStatus
from api.integration import IntegrationAPIError, create_integration_router
from api.schemas import ActionConfirmRequest, ActionDraftRequest, ActionExecuteRequest, ChatRequest
from application import ApplicationContainer
from browser_bridge.service import BrowserBridgeError
from connectors.sis.models import (
    SISLivePreflightRequest,
    SISNavigationRequest,
    SISPreflightRequest,
)
import config
from services.data_protection import DataProtectionUnavailable
from services.library_shadow import (
    ShadowCreateRequest,
    ShadowFeedbackRequest,
    ShadowPreviewRequest,
    ShadowRuleActionRequest,
)


def _dump(model):
    return model.model_dump(mode="json")


def create_api_app(
    container: ApplicationContainer | None = None,
    *,
    db_path: str | Path | None = None,
    integration_token: str | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(lifespan_app: FastAPI):
        shadow = lifespan_app.state.container.library_shadow
        local_binding = library_booking_host_is_loopback()
        if local_binding:
            await shadow.start()
        try:
            yield
        finally:
            if local_binding:
                await shadow.stop()

    app = FastAPI(
        title="HKU AGENTS API",
        version="0.1.0",
        description="Local-first capability and task API for the HKU AGENTS assistant.",
        lifespan=lifespan,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )
    app.state.container = container or ApplicationContainer(db_path=db_path)
    app.state.integration_token = integration_token or config.INTEGRATION_API_TOKEN

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        supplied = request.headers.get("X-Correlation-ID", "")
        request.state.correlation_id = (
            supplied
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied)
            else str(uuid.uuid4())
        )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

    def integration_error_content(
        request: Request,
        *,
        code: str,
        message: str,
        recovery: str | None = None,
        details=None,
    ) -> dict:
        return {
            "api_version": "v1",
            "ok": False,
            "read_only": True,
            "correlation_id": request.state.correlation_id,
            "result": None,
            "task": None,
            "error": {
                "code": code,
                "message": message,
                "recovery": recovery,
                "details": details,
            },
        }

    def require_local_shadow_access(request: Request) -> None:
        client_host = request.client.host if request.client else ""
        try:
            client_is_loopback = ipaddress.ip_address(client_host.strip("[]")).is_loopback
        except ValueError:
            client_is_loopback = client_host.lower() == "localhost"
        origin = request.headers.get("origin")
        origin_is_local = True
        if origin:
            parsed_origin = urlsplit(origin)
            origin_host = parsed_origin.hostname or ""
            try:
                origin_is_local = (
                    parsed_origin.scheme in {"http", "https"}
                    and ipaddress.ip_address(origin_host).is_loopback
                )
            except ValueError:
                origin_is_local = (
                    parsed_origin.scheme in {"http", "https"}
                    and origin_host.lower() == "localhost"
                )
        if not library_booking_host_is_loopback() or not client_is_loopback or not origin_is_local:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "LIBRARY_SHADOW_LOCAL_ONLY",
                    "message": "F3 shadow rules are available only through the loopback local GUI.",
                },
            )

    def shadow_error(exc: Exception) -> HTTPException:
        if isinstance(exc, KeyError):
            return HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})
        if isinstance(exc, DataProtectionUnavailable):
            return HTTPException(
                status_code=503,
                detail={"code": "LIBRARY_SHADOW_PROTECTION_UNAVAILABLE", "message": str(exc)},
            )
        return HTTPException(status_code=409, detail={"code": "LIBRARY_SHADOW_REQUEST_REJECTED", "message": str(exc)})

    @app.exception_handler(IntegrationAPIError)
    async def integration_api_error_handler(request: Request, exc: IntegrationAPIError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content=integration_error_content(
                request,
                code=exc.code,
                message=exc.message,
                recovery=exc.recovery,
            ),
        )

    @app.exception_handler(CapabilityError)
    async def capability_error_handler(_request: Request, exc: CapabilityError):
        status = 404 if exc.code == "CAPABILITY_NOT_FOUND" else 409
        return JSONResponse(status_code=status, content={"error": exc.as_dict()})

    @app.exception_handler(ValidationError)
    async def pydantic_error_handler(_request: Request, exc: ValidationError):
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder({"error": {"code": "INVALID_INPUT", "message": "Input validation failed.", "details": exc.errors()}}),
        )

    @app.exception_handler(RequestValidationError)
    async def request_error_handler(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/v1/integration/"):
            return JSONResponse(
                status_code=422,
                content=jsonable_encoder(
                    integration_error_content(
                        request,
                        code="INVALID_REQUEST",
                        message="Request validation failed.",
                        recovery="Correct the structured tool arguments and retry.",
                        details=exc.errors(),
                    )
                ),
            )
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder({"error": {"code": "INVALID_REQUEST", "message": "Request validation failed.", "details": exc.errors()}}),
        )

    app.include_router(create_integration_router(app.state.integration_token))

    @app.get("/api/v1/health")
    async def health():
        return {
            "status": "ok",
            "service": "hku-agents",
            "version": app.version,
            "mode": "local-first",
        }

    @app.get("/api/v1/capabilities")
    async def capabilities():
        return {"capabilities": [_dump(item) for item in app.state.container.registry.manifests()]}

    @app.get("/api/v1/connections")
    async def connections():
        return {"connections": app.state.container.connection_status()}

    def bridge_http_error(exc: BrowserBridgeError) -> HTTPException:
        status = 504 if exc.code == "BROWSER_TIMEOUT" else 409
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})

    def require_local_pairing_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin and origin not in {
            f"http://{request.url.netloc}",
            f"https://{request.url.netloc}",
        }:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "PAIRING_ORIGIN_REJECTED",
                    "message": "Browser pairing management is limited to the local app origin.",
                },
            )

    @app.get("/api/v1/browser/pairing")
    async def browser_pairing(request: Request):
        require_local_pairing_origin(request)
        if not config.BROWSER_BRIDGE_ENABLED:
            raise HTTPException(status_code=404, detail="Browser bridge is disabled.")
        scheme = "wss" if request.url.scheme == "https" else "ws"
        websocket_url = f"{scheme}://{request.url.netloc}/api/v1/browser/ws"
        return app.state.container.browser_bridge.pairing_info(websocket_url)

    @app.post("/api/v1/browser/pairing/rotate")
    async def rotate_browser_pairing(request: Request):
        require_local_pairing_origin(request)
        if not config.BROWSER_BRIDGE_ENABLED:
            raise HTTPException(status_code=404, detail="Browser bridge is disabled.")
        token = await app.state.container.browser_bridge.rotate_pairing_token()
        scheme = "wss" if request.url.scheme == "https" else "ws"
        return {
            "pairing_token": token,
            "websocket_url": f"{scheme}://{request.url.netloc}/api/v1/browser/ws",
            "pairing_token_source": "runtime_rotated",
            "persistent_across_restarts": False,
        }

    @app.post("/api/v1/browser/pairing/revoke")
    async def revoke_browser_pairing(request: Request):
        require_local_pairing_origin(request)
        if not config.BROWSER_BRIDGE_ENABLED:
            raise HTTPException(status_code=404, detail="Browser bridge is disabled.")
        token = await app.state.container.browser_bridge.revoke_pairing()
        scheme = "wss" if request.url.scheme == "https" else "ws"
        return {
            "pairing_token": token,
            "websocket_url": f"{scheme}://{request.url.netloc}/api/v1/browser/ws",
            "pairing_token_source": "runtime_revoked",
            "persistent_across_restarts": False,
            "extension_pin_cleared": True,
        }

    @app.get("/api/v1/browser/status")
    async def browser_status():
        return app.state.container.connectors["sis_browser"].health()

    @app.get("/api/v1/browser/targets")
    async def browser_targets():
        status = app.state.container.connectors["sis_browser"].health()
        return {
            "read_only": True,
            "bridge_status": status["status"],
            "lifecycle_state": status["lifecycle_state"],
            "targets": status["targets"],
        }

    @app.websocket("/api/v1/browser/ws")
    async def browser_websocket(websocket: WebSocket):
        if not config.BROWSER_BRIDGE_ENABLED:
            await websocket.close(code=4404, reason="Browser bridge is disabled.")
            return
        await app.state.container.browser_bridge.handle_websocket(websocket)

    @app.post("/api/v1/browser/sis/bind")
    async def bind_sis_tab():
        try:
            return await app.state.container.connectors["sis_browser"].bind_tab()
        except BrowserBridgeError as exc:
            raise bridge_http_error(exc) from exc

    @app.post("/api/v1/browser/hku/bind")
    async def bind_hku_tab():
        try:
            return await app.state.container.connectors["sis_browser"].bind_hku_tab()
        except BrowserBridgeError as exc:
            raise bridge_http_error(exc) from exc

    @app.post("/api/v1/browser/hku/open-sis")
    async def open_sis_from_portal():
        try:
            return await app.state.container.connectors["sis_browser"].open_sis()
        except BrowserBridgeError as exc:
            raise bridge_http_error(exc) from exc

    @app.post("/api/v1/browser/hku/open-moodle")
    async def open_moodle_from_portal():
        try:
            return await app.state.container.connectors["sis_browser"].open_moodle()
        except BrowserBridgeError as exc:
            raise bridge_http_error(exc) from exc

    @app.get("/api/v1/browser/moodle/dashboard")
    async def inspect_moodle_dashboard():
        try:
            return await app.state.container.connectors[
                "sis_browser"
            ].inspect_moodle_dashboard()
        except BrowserBridgeError as exc:
            raise bridge_http_error(exc) from exc

    @app.get("/api/v1/browser/moodle/courses")
    async def list_moodle_courses():
        try:
            return await app.state.container.connectors[
                "sis_browser"
            ].list_moodle_courses()
        except BrowserBridgeError as exc:
            raise bridge_http_error(exc) from exc

    @app.get("/api/v1/browser/moodle/assignments")
    async def list_moodle_upcoming_assignments():
        try:
            return await app.state.container.connectors[
                "sis_browser"
            ].list_moodle_upcoming_assignments()
        except BrowserBridgeError as exc:
            raise bridge_http_error(exc) from exc

    @app.post("/api/v1/browser/sis/open-enrollment-add-classes")
    async def open_enrollment_add_classes(body: SISNavigationRequest | None = None):
        try:
            return await app.state.container.connectors[
                "sis_browser"
            ].open_enrollment_add_classes(body.term_label if body else None)
        except BrowserBridgeError as exc:
            raise bridge_http_error(exc) from exc

    @app.get("/api/v1/browser/sis/page")
    async def inspect_sis_page():
        try:
            return await app.state.container.connectors["sis_browser"].inspect_page()
        except BrowserBridgeError as exc:
            raise bridge_http_error(exc) from exc

    @app.get("/api/v1/browser/sis/cart")
    async def inspect_sis_cart():
        try:
            return await app.state.container.connectors["sis_browser"].inspect_cart()
        except BrowserBridgeError as exc:
            raise bridge_http_error(exc) from exc

    @app.post("/api/v1/chat")
    async def chat(body: ChatRequest):
        record = await app.state.container.tasks.submit_and_wait(
            "knowledge.answer",
            {"message": body.message, "history": body.history},
            session_id=body.session_id,
        )
        if record.status != TaskStatus.COMPLETED:
            raise HTTPException(status_code=502, detail={"task_id": record.id, "error": record.error})
        return {"task_id": record.id, **(record.result or {})}

    @app.post("/api/v1/actions/draft")
    async def create_draft(body: ActionDraftRequest):
        draft = app.state.container.actions.create_draft(body.capability, body.input)
        return _dump(draft)

    @app.post("/api/v1/actions/{draft_id}/validate")
    async def validate_draft(draft_id: str):
        try:
            return _dump(app.state.container.actions.validate_draft(draft_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="Action draft not found.")

    @app.post("/api/v1/actions/{draft_id}/confirm")
    async def confirm_draft(draft_id: str, body: ActionConfirmRequest):
        try:
            draft, token = app.state.container.actions.confirm(draft_id, body.preview_digest)
        except KeyError:
            raise HTTPException(status_code=404, detail="Action draft not found.")
        return {"draft": _dump(draft), "confirmation_token": token}

    @app.post("/api/v1/actions/{draft_id}/execute", status_code=202)
    async def execute_draft(draft_id: str, body: ActionExecuteRequest):
        try:
            task = app.state.container.actions.execute(
                draft_id,
                confirmation_token=body.confirmation_token,
                session_id=body.session_id,
                correlation_id=body.correlation_id,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Action draft not found.")
        return _dump(task)

    @app.get("/api/v1/library/shadow/status")
    async def library_shadow_status(request: Request):
        require_local_shadow_access(request)
        shadow = app.state.container.library_shadow
        return {
            "enabled": shadow.enabled,
            "scheduler_running": shadow.running,
            "loopback_binding_required": True,
            "mode": "shadow_only",
            "booking_authority": False,
            "booking_executor_available": False,
            "booking_writes_performed": 0,
            "policy_change_detection_scope": "local_verified_catalog_digest_only",
            "maximum_active_rules": 5,
            "data_protection": "windows_current_user_dpapi" if shadow.enabled else "unavailable",
            "unavailable_reason": shadow.protection_error,
        }

    @app.post("/api/v1/library/shadow/rules/preview")
    async def preview_library_shadow_rule(body: ShadowPreviewRequest, request: Request):
        require_local_shadow_access(request)
        try:
            return app.state.container.library_shadow.preview(body)
        except Exception as exc:
            raise shadow_error(exc) from exc

    @app.post("/api/v1/library/shadow/rules")
    async def create_library_shadow_rule(body: ShadowCreateRequest, request: Request):
        require_local_shadow_access(request)
        try:
            return app.state.container.library_shadow.create_rule(body)
        except Exception as exc:
            raise shadow_error(exc) from exc

    @app.get("/api/v1/library/shadow/rules")
    async def list_library_shadow_rules(request: Request):
        require_local_shadow_access(request)
        try:
            return app.state.container.library_shadow.list_rules()
        except Exception as exc:
            raise shadow_error(exc) from exc

    @app.post("/api/v1/library/shadow/rules/{rule_id}/{action}")
    async def change_library_shadow_rule(
        rule_id: str, action: str, body: ShadowRuleActionRequest, request: Request,
    ):
        require_local_shadow_access(request)
        if action not in {"pause", "resume", "revoke"}:
            raise HTTPException(status_code=404, detail="Unknown shadow-rule action.")
        if action == "revoke" and not body.revoke_acknowledged:
            raise HTTPException(
                status_code=409,
                detail={"code": "LIBRARY_SHADOW_REVOKE_NOT_ACKNOWLEDGED", "message": "Explicit revoke acknowledgment is required."},
            )
        try:
            return app.state.container.library_shadow.change_rule_state(rule_id, action)
        except Exception as exc:
            raise shadow_error(exc) from exc

    @app.get("/api/v1/library/shadow/runs")
    async def list_library_shadow_runs(
        request: Request,
        rule_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        require_local_shadow_access(request)
        try:
            return app.state.container.library_shadow.list_runs(rule_id, limit)
        except Exception as exc:
            raise shadow_error(exc) from exc

    @app.post("/api/v1/library/shadow/runs/{run_id}/feedback")
    async def record_library_shadow_feedback(
        run_id: str, body: ShadowFeedbackRequest, request: Request,
    ):
        require_local_shadow_access(request)
        try:
            return app.state.container.library_shadow.record_feedback(run_id, body)
        except Exception as exc:
            raise shadow_error(exc) from exc

    @app.get("/api/v1/tasks")
    async def list_tasks(limit: int = Query(default=50, ge=1, le=200)):
        return {"tasks": [_dump(item) for item in app.state.container.store.list_tasks(limit)]}

    @app.get("/api/v1/tasks/{task_id}")
    async def get_task(task_id: str):
        try:
            return _dump(app.state.container.store.get_task(task_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="Task not found.")

    @app.post("/api/v1/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str):
        try:
            return _dump(app.state.container.tasks.cancel(task_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="Task not found.")

    @app.get("/api/v1/tasks/{task_id}/events")
    async def task_events(task_id: str, after: int = Query(default=0, ge=0)):
        try:
            app.state.container.store.get_task(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Task not found.")

        async def stream():
            sequence = after
            while True:
                events = app.state.container.store.list_task_events(task_id, sequence)
                for event in events:
                    sequence = event.sequence
                    payload = json.dumps(_dump(event), ensure_ascii=False, separators=(",", ":"))
                    yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {payload}\n\n"
                task = app.state.container.store.get_task(task_id)
                if task.status in TERMINAL_TASK_STATUSES and not events:
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/v1/audit")
    async def audit(limit: int = Query(default=100, ge=1, le=500)):
        return {"events": [_dump(item) for item in app.state.container.store.list_audit_events(limit)]}

    @app.post("/api/v1/sis/preflight")
    async def sis_preflight(body: SISPreflightRequest):
        record = await app.state.container.tasks.submit_and_wait(
            "sis.enrollment.preflight",
            body.model_dump(mode="json"),
        )
        return {"task": _dump(record), "result": record.result}

    @app.post("/api/v1/browser/sis/preflight")
    async def live_sis_preflight(body: SISLivePreflightRequest):
        record = await app.state.container.tasks.submit_and_wait(
            "sis.enrollment.live_preflight",
            body.model_dump(mode="json"),
        )
        return {"task": _dump(record), "result": record.result}

    @app.post("/api/v1/browser/sis/navigate-and-preflight")
    async def navigate_and_preflight(body: SISLivePreflightRequest):
        record = await app.state.container.tasks.submit_and_wait(
            "sis.enrollment.navigate_and_preflight",
            body.model_dump(mode="json"),
        )
        return {"task": _dump(record), "result": record.result}

    return app
