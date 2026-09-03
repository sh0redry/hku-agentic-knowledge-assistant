from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from agents.errors import CapabilityError
from agents.models import TERMINAL_TASK_STATUSES, TaskStatus
from api.schemas import ActionConfirmRequest, ActionDraftRequest, ActionExecuteRequest, ChatRequest
from application import ApplicationContainer
from connectors.sis.models import SISPreflightRequest


def _dump(model):
    return model.model_dump(mode="json")


def create_api_app(
    container: ApplicationContainer | None = None,
    *,
    db_path: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title="HKU AGENTS API",
        version="0.1.0",
        description="Local-first capability and task API for the HKU AGENTS assistant.",
    )
    app.state.container = container or ApplicationContainer(db_path=db_path)

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
    async def request_error_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder({"error": {"code": "INVALID_REQUEST", "message": "Request validation failed.", "details": exc.errors()}}),
        )

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

    return app
