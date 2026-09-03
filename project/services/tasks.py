from __future__ import annotations

import asyncio
import uuid

from pydantic import ValidationError

from agents.errors import CapabilityError, ExecutionUnknownError
from agents.models import ExecutionContext, TaskRecord, TaskStatus, utc_now
from agents.registry import CapabilityRegistry
from services.store import SQLiteStore


class TaskManager:
    def __init__(self, registry: CapabilityRegistry, store: SQLiteStore):
        self.registry = registry
        self.store = store
        self._running: dict[str, asyncio.Task] = {}
        self._inputs: dict[str, dict] = {}
        self._results: dict[str, dict] = {}

    def create(self, capability_id: str, payload: dict, correlation_id: str | None = None) -> TaskRecord:
        capability = self.registry.get(capability_id)
        validated = capability.validate_input(payload)
        now = utc_now()
        record = TaskRecord(
            id=str(uuid.uuid4()),
            capability=capability_id,
            status=TaskStatus.QUEUED,
            phase="queued",
            input=capability.persisted_input(validated),
            correlation_id=correlation_id or str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
        )
        self.store.create_task(record)
        self.store.add_task_event(record.id, "task.queued", {"status": record.status.value})
        self.store.add_audit_event(capability_id, "task.created", {}, record.id)
        self._inputs[record.id] = validated.model_dump(mode="python")
        return record

    def start(self, task_id: str, session_id: str = "local-user") -> asyncio.Task:
        if task_id in self._running:
            return self._running[task_id]
        background = asyncio.create_task(self._execute(task_id, session_id))
        self._running[task_id] = background
        background.add_done_callback(lambda _: self._running.pop(task_id, None))
        return background

    async def submit_and_wait(
        self,
        capability_id: str,
        payload: dict,
        *,
        session_id: str = "local-user",
        correlation_id: str | None = None,
    ) -> TaskRecord:
        record = self.create(capability_id, payload, correlation_id)
        await self.start(record.id, session_id)
        completed = self.store.get_task(record.id)
        if record.id in self._results:
            completed.result = self._results.pop(record.id)
        return completed

    async def _execute(self, task_id: str, session_id: str) -> None:
        record = self.store.get_task(task_id)
        capability = self.registry.get(record.capability)
        if record.cancel_requested:
            self._transition(task_id, TaskStatus.CANCELLED, "cancelled")
            return

        self._transition(task_id, TaskStatus.RUNNING, "validating")
        try:
            execution_input = self._inputs.pop(task_id, record.input)
            validated = capability.validate_input(execution_input)
            if self.store.get_task(task_id).cancel_requested:
                self._transition(task_id, TaskStatus.CANCELLED, "cancelled")
                return
            self.store.update_task(task_id, phase="executing")
            self.store.add_task_event(task_id, "task.executing", {})
            context = ExecutionContext(
                task_id=task_id,
                session_id=session_id,
                correlation_id=record.correlation_id,
            )
            result = await asyncio.wait_for(
                capability.execute(validated, context),
                timeout=capability.manifest.timeout_seconds,
            )
            persisted_result = capability.persisted_result(result)
            if persisted_result != result:
                self._results[task_id] = result
            self.store.update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                phase="completed",
                result=persisted_result,
            )
            self.store.add_task_event(task_id, "task.completed", {"result": persisted_result})
            self.store.add_audit_event(record.capability, "task.completed", {}, task_id)
        except ExecutionUnknownError as exc:
            self._fail(task_id, TaskStatus.UNKNOWN, "manual_verification_required", exc.as_dict())
        except CapabilityError as exc:
            self._fail(task_id, TaskStatus.FAILED, "failed", exc.as_dict())
        except ValidationError as exc:
            self._fail(
                task_id,
                TaskStatus.FAILED,
                "validation_failed",
                {"code": "INVALID_INPUT", "message": "Capability input is invalid.", "details": exc.errors()},
            )
        except asyncio.TimeoutError:
            self._fail(
                task_id,
                TaskStatus.FAILED,
                "timed_out",
                {"code": "CAPABILITY_TIMEOUT", "message": "Capability execution timed out."},
            )
        except Exception as exc:
            self._fail(
                task_id,
                TaskStatus.FAILED,
                "failed",
                {"code": "INTERNAL_ERROR", "message": str(exc)},
            )

    def _transition(self, task_id: str, status: TaskStatus, phase: str) -> None:
        self.store.update_task(task_id, status=status, phase=phase)
        self.store.add_task_event(task_id, f"task.{status.value}", {"status": status.value, "phase": phase})

    def _fail(self, task_id: str, status: TaskStatus, phase: str, error: dict) -> None:
        record = self.store.update_task(task_id, status=status, phase=phase, error=error)
        self.store.add_task_event(task_id, f"task.{status.value}", {"error": error})
        self.store.add_audit_event(record.capability, f"task.{status.value}", {"code": error.get("code")}, task_id)

    def cancel(self, task_id: str) -> TaskRecord:
        record = self.store.get_task(task_id)
        if record.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
            record = self.store.update_task(task_id, cancel_requested=True)
            self.store.add_task_event(task_id, "task.cancel_requested", {})
        return record
