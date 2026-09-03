from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import timedelta

import config
from agents.errors import CapabilityError, PolicyDeniedError
from agents.models import ActionDraft, TaskStatus, utc_now
from agents.registry import CapabilityRegistry
from services.policy import PolicyEngine
from services.store import SQLiteStore
from services.tasks import TaskManager


def _digest(value: dict) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ActionService:
    def __init__(
        self,
        registry: CapabilityRegistry,
        store: SQLiteStore,
        tasks: TaskManager,
        policy: PolicyEngine,
    ):
        self.registry = registry
        self.store = store
        self.tasks = tasks
        self.policy = policy

    def create_draft(self, capability_id: str, payload: dict) -> ActionDraft:
        capability = self.registry.get(capability_id)
        validated = capability.validate_input(payload)
        preview = capability.preview(validated)
        now = utc_now()
        if not self.policy.confirmation_required(capability.manifest):
            raise PolicyDeniedError(
                "DRAFT_NOT_REQUIRED",
                "Read-only capabilities execute directly and do not create persistent action drafts.",
            )
        status = TaskStatus.AWAITING_CONFIRMATION
        draft = ActionDraft(
            id=str(uuid.uuid4()),
            capability=capability_id,
            status=status,
            input=validated.model_dump(mode="json"),
            preview=preview,
            preview_digest=_digest(preview),
            created_at=now,
            updated_at=now,
        )
        self.store.save_draft(draft)
        self.store.add_audit_event(
            capability_id,
            "action.drafted",
            {"preview_digest": draft.preview_digest, "risk": capability.manifest.risk.value},
        )
        return draft

    def validate_draft(self, draft_id: str) -> ActionDraft:
        draft, token_hash = self.store.get_draft_with_token_hash(draft_id)
        capability = self.registry.get(draft.capability)
        validated = capability.validate_input(draft.input)
        preview = capability.preview(validated)
        digest = _digest(preview)
        if digest != draft.preview_digest:
            raise CapabilityError(
                "PREVIEW_CHANGED",
                "The action preview changed and must be reviewed again.",
            )
        draft.preview = preview
        draft.updated_at = utc_now()
        self.store.save_draft(draft, token_hash)
        return draft

    def confirm(self, draft_id: str, preview_digest: str) -> tuple[ActionDraft, str]:
        draft = self.validate_draft(draft_id)
        capability = self.registry.get(draft.capability)
        if not self.policy.confirmation_required(capability.manifest):
            raise PolicyDeniedError(
                "CONFIRMATION_NOT_REQUIRED",
                "This read-only action does not require a confirmation token.",
            )
        if not hmac.compare_digest(draft.preview_digest, preview_digest):
            raise PolicyDeniedError(
                "PREVIEW_MISMATCH",
                "The confirmed preview does not match the current action draft.",
            )
        token = secrets.token_urlsafe(32)
        now = utc_now()
        draft.status = TaskStatus.QUEUED
        draft.confirmation_expires_at = now + timedelta(seconds=config.CONFIRMATION_TTL_SECONDS)
        draft.updated_at = now
        self.store.save_draft(draft, _token_hash(token))
        self.store.add_audit_event(
            draft.capability,
            "action.confirmed",
            {"preview_digest": draft.preview_digest, "expires_at": draft.confirmation_expires_at.isoformat()},
        )
        return draft, token

    def execute(
        self,
        draft_id: str,
        *,
        confirmation_token: str | None,
        session_id: str,
        correlation_id: str | None = None,
    ):
        draft, stored_hash = self.store.get_draft_with_token_hash(draft_id)
        capability = self.registry.get(draft.capability)
        requires_confirmation = self.policy.confirmation_required(capability.manifest)
        confirmed = not requires_confirmation
        if requires_confirmation:
            if draft.status != TaskStatus.QUEUED or not draft.confirmation_expires_at:
                raise PolicyDeniedError("CONFIRMATION_REQUIRED", "The action has not been confirmed.")
            if draft.confirmation_expires_at <= utc_now():
                raise PolicyDeniedError("CONFIRMATION_EXPIRED", "The action confirmation has expired.")
            if not confirmation_token or not stored_hash or not hmac.compare_digest(
                _token_hash(confirmation_token), stored_hash
            ):
                raise PolicyDeniedError("INVALID_CONFIRMATION", "The confirmation token is invalid.")
            confirmed = True
        self.policy.assert_executable(capability.manifest, confirmed=confirmed)
        if draft.status == TaskStatus.RUNNING:
            raise PolicyDeniedError("DRAFT_ALREADY_USED", "This action draft has already been executed.")
        draft.status = TaskStatus.RUNNING
        draft.updated_at = utc_now()
        self.store.save_draft(draft, None)
        task = self.tasks.create(draft.capability, draft.input, correlation_id)
        self.tasks.start(task.id, session_id)
        self.store.add_audit_event(
            draft.capability,
            "action.executed",
            {"draft_id": draft.id, "preview_digest": draft.preview_digest},
            task.id,
        )
        return task
