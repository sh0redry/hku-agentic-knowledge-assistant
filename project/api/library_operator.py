"""Fixed Desktop operator workflows; never a generic task/HTTP proxy."""
from __future__ import annotations

import asyncio
import ipaddress
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from agents.errors import CapabilityError
from agents.models import TaskStatus
from agents.library.agent import (
    LibrarySpaceBookRequest, LibrarySpaceBookingPreviewRequest,
    LibrarySpaceAvailabilityRequest, LibrarySpaceDateOptionsRequest,
    library_booking_host_is_loopback,
)
from services.library_shadow import ShadowPreviewRequest, ShadowCreateRequest, ShadowFeedbackRequest
from services.library_autobook import (
    AutobookPilotDraft, AutobookDraftCreateRequest, AutobookAuthorizationCreateRequest,
)


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ObjectID(Empty):
    id: str = Field(pattern=r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class RuleAction(ObjectID):
    action: Literal["pause", "resume", "revoke"]
    revoke_acknowledged: bool = False


class AuthorizationAction(ObjectID):
    action: Literal["pause", "revoke"]


class ExecutorConfig(Empty):
    enabled: bool
    dry_run: bool
    operator_acknowledged: Literal[True]


class BookingGateConfig(Empty):
    enabled: bool
    operator_acknowledged: Literal[True]


class ArmAuthorization(ObjectID):
    arming_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_booking_acknowledged: Literal[True]
    future_booking_acknowledged: Literal[True]
    policy_acceptance_acknowledged: Literal[True]
    discussion_room_rules_acknowledged: Literal[True]


class RunFeedback(ObjectID):
    feedback: ShadowFeedbackRequest


class ExecuteBooking(ObjectID):
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    exact_booking_acknowledged: Literal[True]


class OperatorRequest(Empty):
    operation: Literal[
        "dates", "availability", "preview", "booking_prepare", "booking_execute", "booking_result",
        "shadow_status", "shadow_preview", "shadow_create", "shadow_rules", "shadow_action",
        "shadow_runs", "shadow_feedback", "f4_draft_preview", "f4_draft_create", "f4_drafts",
        "f4_draft_revoke", "f4_authorization_preview", "f4_authorization_create",
        "f4_authorizations", "f4_authorization_action",
        "f4_executor_status", "f4_executor_configure", "f4_authorization_arm",
        "booking_gate_status", "booking_gate_configure",
    ]
    input: dict = Field(default_factory=dict)


MODELS = {
    "dates": LibrarySpaceDateOptionsRequest, "availability": LibrarySpaceAvailabilityRequest,
    "preview": LibrarySpaceBookingPreviewRequest, "booking_prepare": LibrarySpaceBookRequest,
    "booking_execute": ExecuteBooking, "booking_result": ObjectID,
    "shadow_status": Empty, "shadow_preview": ShadowPreviewRequest, "shadow_create": ShadowCreateRequest,
    "shadow_rules": Empty, "shadow_action": RuleAction, "shadow_runs": Empty, "shadow_feedback": RunFeedback,
    "f4_draft_preview": AutobookPilotDraft, "f4_draft_create": AutobookDraftCreateRequest,
    "f4_drafts": Empty, "f4_draft_revoke": ObjectID,
    "f4_authorization_preview": AutobookPilotDraft, "f4_authorization_create": AutobookAuthorizationCreateRequest,
    "f4_authorizations": Empty, "f4_authorization_action": AuthorizationAction,
    "f4_executor_status": Empty, "f4_executor_configure": ExecutorConfig,
    "f4_authorization_arm": ArmAuthorization,
    "booking_gate_status": Empty, "booking_gate_configure": BookingGateConfig,
}


def install_library_operator(router, authorize):
    from api.integration import IntegrationAPIError
    from pydantic import ValidationError
    from services.data_protection import DataProtectionUnavailable

    # Serializes the human confirmation/execute transition for this UI channel.
    execution_lock = asyncio.Lock()

    def local(request):
        def loopback(host):
            try:
                return ipaddress.ip_address(host.strip("[]")).is_loopback
            except ValueError:
                return host == "localhost"
        host = request.client.host if request.client else ""
        origin = request.headers.get("origin")
        origin_ok = not origin or (
            urlsplit(origin).scheme in {"http", "https"} and loopback(urlsplit(origin).hostname or "")
        )
        if not library_booking_host_is_loopback() or not loopback(host) or not origin_ok:
            raise IntegrationAPIError(403, "LIBRARY_OPERATOR_LOCAL_ONLY", "Desktop operator access requires loopback.")

    @router.post("/library/operator")
    async def operator(request: Request, correlation_id: str = Depends(authorize)):
        local(request)
        if len(await request.body()) > 16384:
            raise IntegrationAPIError(413, "INVALID_REQUEST", "Operator request is too large.")
        try:
            body = OperatorRequest.model_validate(await request.json())
            model = MODELS[body.operation].model_validate(body.input)
            op = body.operation
            container = request.app.state.container
            shadow = container.library_shadow
            f4 = container.library_autobook
            executor = container.library_autobook_executor
            task_id = None
            if op in {"dates", "availability", "preview"}:
                capability = {"dates": "library.spaces.list_dates", "availability": "library.spaces.search_availability",
                              "preview": "library.spaces.booking_preview"}[op]
                task = await container.tasks.submit_and_wait(capability, model.model_dump(mode="json"),
                                                            correlation_id=correlation_id)
                task_id = task.id
                if task.status != TaskStatus.COMPLETED:
                    code = (task.error or {}).get("code", "LIBRARY_READ_FAILED")
                    raise IntegrationAPIError(409, code, "Library read failed; this is not an empty result.")
                result = task.result or {}
            elif op == "booking_prepare":
                draft = container.actions.create_draft("library.spaces.book", model.model_dump(mode="json"))
                result = {"id": draft.id, "preview_digest": draft.preview_digest, "preview": draft.preview,
                          "state": "awaiting_exact_confirmation", "booking_writes_performed": 0}
            elif op == "booking_execute":
                async with execution_lock:
                    draft = container.store.get_draft_with_token_hash(model.id)[0]
                    if draft.capability != "library.spaces.book" or draft.status != TaskStatus.AWAITING_CONFIRMATION:
                        raise IntegrationAPIError(409, "DRAFT_ALREADY_USED", "Do not retry a consumed booking draft.")
                    draft, token = container.actions.confirm(model.id, model.preview_digest)
                    task = container.actions.execute(model.id, confirmation_token=token,
                                                     session_id="desktop-library-operator", correlation_id=correlation_id)
                    task_id = task.id
                    result = {"task_id": task.id, "state": task.status.value, "phase": task.phase,
                              "booking_success_verified": False, "submission_requested": True}
            elif op == "booking_result":
                task = container.store.get_task(model.id)
                if task is None or task.capability != "library.spaces.book":
                    raise IntegrationAPIError(404, "NOT_FOUND", "Not a Library booking task.")
                task_id = task.id
                result = {"task_id": task.id, "state": task.status.value, "phase": task.phase,
                          "result": task.result, "error_code": (task.error or {}).get("code")}
            elif op in {"booking_gate_status", "booking_gate_configure"}:
                import config
                if op == "booking_gate_configure":
                    config.LIBRARY_BOOKING_WRITES_ENABLED = model.enabled
                    capability = container.registry.get("library.spaces.book")
                    capability.manifest = capability.manifest.model_copy(update={"availability":
                        "supervised_one_shot_confirmation" if model.enabled else "disabled_pending_operator_enablement"})
                    container.store.add_audit_event("library.spaces.book", "operator_gate_configured", {"enabled": model.enabled})
                result = {"external_submission_enabled": config.LIBRARY_BOOKING_WRITES_ENABLED,
                          "effect": "F2 gate only; every booking still needs a fresh exact preview and confirmation. Core restart uses launcher defaults."}
            elif op == "shadow_status":
                result = {"enabled": shadow.enabled, "scheduler_running": shadow.running,
                          "shadow_only": True, "booking_authority": False}
            elif op == "shadow_preview": result = shadow.preview(model)
            elif op == "shadow_create": result = shadow.create_rule(model)
            elif op == "shadow_rules": result = shadow.list_rules()
            elif op == "shadow_runs": result = shadow.list_runs(None, 50)
            elif op == "shadow_action":
                if model.action == "revoke" and not model.revoke_acknowledged:
                    raise IntegrationAPIError(409, "REVOKE_ACKNOWLEDGMENT_REQUIRED", "Review and acknowledge revocation.")
                result = shadow.change_rule_state(model.id, model.action)
            elif op == "shadow_feedback": result = shadow.record_feedback(model.id, model.feedback)
            elif op == "f4_draft_preview": result = f4.preview(model)
            elif op == "f4_draft_create": result = f4.create(model)
            elif op == "f4_drafts": result = f4.list()
            elif op == "f4_draft_revoke": result = f4.revoke(model.id)
            elif op == "f4_authorization_preview": result = f4.authorization_preview(model)
            elif op == "f4_authorization_create":
                created = f4.create_authorization(model)
                result = executor.public(executor._row(created["id"]))
            elif op == "f4_authorizations": result = executor.list()
            elif op == "f4_authorization_action": result = executor.disarm(model.id, model.action)
            elif op == "f4_executor_status": result = executor.status()
            elif op == "f4_executor_configure": result = executor.configure(enabled=model.enabled, dry_run=model.dry_run)
            elif op == "f4_authorization_arm": result = executor.arm(model.id, model.arming_digest)
            else: raise IntegrationAPIError(400, "INVALID_REQUEST", "Unsupported operation.")
            return {"ok": True, "operation": op, "result": result, "task_id": task_id,
                    "correlation_id": correlation_id, "execution_enabled": executor.enabled if op.startswith("f4_") else None}
        except IntegrationAPIError:
            raise
        except (ValidationError, ValueError, TypeError):
            raise IntegrationAPIError(422, "INVALID_OPERATOR_INPUT", "Check exact inputs, preview expiry and time ordering; preview again after changes.")
        except KeyError:
            raise IntegrationAPIError(404, "NOT_FOUND", "The selected record is unavailable.")
        except DataProtectionUnavailable:
            raise IntegrationAPIError(409, "DATA_PROTECTION_UNAVAILABLE", "Current-user Windows data protection is required.")
        except CapabilityError as exc:
            raise IntegrationAPIError(409, exc.code, "Core refused this operation. Check policy, preview and booking gate.")
