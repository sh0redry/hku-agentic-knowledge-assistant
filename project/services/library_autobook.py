"""F4 reviewed drafts and encrypted advance authorizations; arming is separate."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.models import utc_now
from services.library_shadow import (
    LibraryShadowRuleDefinition,
    LibraryShadowScheduler,
    ShadowRoomPreference,
    ShadowSessionPreference,
)
from services.data_protection import DataProtectionUnavailable, WindowsUserDataProtector
from services.store import SQLiteStore


class AutobookPilotDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_type: Literal["discussion_room"]
    target_date: date
    prepare_at: datetime
    execution_at: datetime
    stop_at: datetime
    floor: Literal["Level 3"]
    room: str = Field(min_length=1, max_length=200)
    start_time: str
    end_time: str
    eligibility_category: Literal[
        "current_hku_students", "current_hku_staff",
        "current_hku_space_students", "current_hku_space_staff",
    ]
    poll_interval_seconds: int = Field(default=15, ge=15, le=120)
    max_date_checks: int = Field(default=8, ge=1, le=20)

    @model_validator(mode="after")
    def exact_pilot_scope(self):
        if not self.room.startswith("Discussion Room ") or not self.room.removeprefix("Discussion Room ").isdigit():
            raise ValueError("The F4 pilot requires one exact Main Library Discussion Room label.")
        normalized = LibraryShadowRuleDefinition.model_validate({
            "facility_type": self.facility_type,
            "target_date": self.target_date,
            "prepare_at": self.prepare_at,
            "execution_at": self.execution_at,
            "stop_at": self.stop_at,
            "room_preference_order": [ShadowRoomPreference(floor=self.floor, room=self.room)],
            "session_preference_order": [ShadowSessionPreference(start_time=self.start_time, end_time=self.end_time)],
            "eligibility_category": self.eligibility_category,
            "poll_interval_seconds": self.poll_interval_seconds,
            "max_date_checks": self.max_date_checks,
            "shadow_only": True,
        })
        self.prepare_at = normalized.prepare_at
        self.execution_at = normalized.execution_at
        self.stop_at = normalized.stop_at
        if not self.execution_at.date() <= self.target_date <= self.execution_at.date() + timedelta(days=1):
            raise ValueError("The F4 pilot targets only execution-day or next-day facilities; live dates must also offer the exact date.")
        if (int(self.end_time[:2]) * 60 + int(self.end_time[3:]) -
                int(self.start_time[:2]) * 60 - int(self.start_time[3:])) != 60:
            raise ValueError("The F4 discussion-room pilot requires one exact 60-minute session.")
        return self


def preview_autobook_pilot(draft: AutobookPilotDraft) -> dict:
    """Locally review a proposed exact target without creating an authorization."""
    from agents.library.agent import LibrarySpaceBookingPreviewCapability

    now = utc_now()
    shadow = LibraryShadowRuleDefinition.model_validate({
        "facility_type": draft.facility_type,
        "target_date": draft.target_date,
        "prepare_at": draft.prepare_at,
        "execution_at": draft.execution_at,
        "stop_at": draft.stop_at,
        "room_preference_order": [{"floor": draft.floor, "room": draft.room}],
        "session_preference_order": [{"start_time": draft.start_time, "end_time": draft.end_time}],
        "eligibility_category": draft.eligibility_category,
        "poll_interval_seconds": draft.poll_interval_seconds,
        "max_date_checks": draft.max_date_checks,
        "shadow_only": True,
    })
    LibraryShadowScheduler._exact_execution(now, shadow)
    facility = LibraryShadowScheduler._facility_policy(draft.facility_type)
    if draft.eligibility_category not in facility.get("eligibility", []):
        raise ValueError("The declared eligibility category is not listed for this facility.")
    policy_facts = {
        "verified_on": LibrarySpaceBookingPreviewCapability.POLICY_VERIFIED_ON,
        "policy_sources": LibrarySpaceBookingPreviewCapability.POLICY_SOURCES,
        "facility": facility,
    }
    policy_digest = hashlib.sha256(json.dumps(policy_facts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {
        "ok": True,
        "phase": "f4_design_preview_only",
        "read_only": True,
        "standing_authorization_created": False,
        "unattended_submission_enabled": False,
        "booking_writes_performed": 0,
        "browser_interactions_performed": False,
        "pilot_scope": {
            "location": "Main Library", "facility_type": draft.facility_type,
            "booking_facility_type": "Discussion Room", "target_date": draft.target_date.isoformat(),
            "floor": draft.floor, "room": draft.room,
            "start_time": draft.start_time, "end_time": draft.end_time,
            "prepare_at_hong_kong": shadow.prepare_at.isoformat(),
            "checks_start_at_hong_kong": shadow.execution_at.isoformat(),
            "stop_at_hong_kong": shadow.stop_at.isoformat(),
            "poll_interval_seconds": draft.poll_interval_seconds,
            "max_date_checks": draft.max_date_checks,
            "maximum_successful_bookings": 1,
            "fallback_rooms_or_times_allowed": False,
            "eligibility_category": draft.eligibility_category,
            "eligibility_basis": "self_declared_not_account_verified",
        },
        "policy_digest": policy_digest,
        "policy_verified_on": policy_facts["verified_on"],
        "policy_sources": LibrarySpaceBookingPreviewCapability.POLICY_SOURCES,
        "unmet_gates": [
            "F3.2b live date-transition/release-window acceptance is pending.",
            "Eligibility is user-attested, not account-category verified. Execution requires a verifiably empty target day and an exact authoritative booking-record match.",
            "The guarded F4 executor requires separate local runtime enablement and exact authorization arming.",
        ],
        "non_blocking_notes": [
            "Automated-use permission is unverified and is not an engineering gate at the user's direction."
        ],
    }


class AutobookDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    non_authorizing_acknowledged: Literal[True]


class AutobookAuthorizationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    future_booking_acknowledged: Literal[True]
    policy_acceptance_acknowledged: Literal[True]
    discussion_room_rules_acknowledged: Literal[True]


class AutobookAuthorizationActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["pause", "revoke"]


class LibraryAutobookDraftService:
    """Stores reviewed F4 ideas; creating a record alone never arms the executor."""

    def __init__(self, store: SQLiteStore, protector=None):
        self.store = store
        self._lock = threading.Lock()
        self._key = secrets.token_bytes(32)
        self._previews: dict[str, tuple[AutobookPilotDraft, datetime, str]] = {}
        self._authorization_previews: dict[str, tuple[AutobookPilotDraft, datetime, str]] = {}
        self.protection_error = None
        try:
            self._protector = protector if protector is not None else WindowsUserDataProtector()
        except DataProtectionUnavailable as exc:
            self._protector = None
            self.protection_error = str(exc)

    def _require_protection(self):
        if self._protector is None:
            raise DataProtectionUnavailable(self.protection_error or "F4 draft protection is unavailable.")
        return self._protector

    def preview(self, draft: AutobookPilotDraft) -> dict:
        self._require_protection()
        result = preview_autobook_pilot(draft)
        now = utc_now()
        expires = now + timedelta(minutes=10)
        nonce = secrets.token_hex(16)
        canonical = draft.model_dump_json()
        digest = hmac.new(self._key, (nonce + canonical + result["policy_digest"]).encode(), hashlib.sha256).hexdigest()
        with self._lock:
            self._previews = {key: value for key, value in self._previews.items() if value[1] > now}
            self._previews[digest] = (draft, expires, result["policy_digest"])
        return {**result, "phase": "f4_non_authorizing_draft_preview", "preview_digest": digest,
                "preview_expires_at": expires.isoformat(), "booking_authority": False}

    def create(self, request: AutobookDraftCreateRequest) -> dict:
        protector = self._require_protection()
        with self._lock:
            entry = self._previews.pop(request.preview_digest, None)
        if entry is None:
            raise ValueError("F4 draft preview is missing or already consumed; preview again.")
        draft, expires, policy_digest = entry
        if expires <= utc_now():
            raise ValueError("F4 draft preview expired; preview again.")
        current = preview_autobook_pilot(draft)
        if current["policy_digest"] != policy_digest:
            raise ValueError("F4 facility policy changed; preview again.")
        now = utc_now()
        record_id = str(uuid.uuid4())
        payload = {"draft": draft.model_dump(mode="json"), "policy_digest": policy_digest,
                   "non_authorizing_acknowledged": True}
        encrypted = protector.protect(json.dumps(payload, sort_keys=True).encode())
        self.store.create_library_autobook_draft({
            "id": record_id, "encrypted_payload": encrypted,
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
            "expires_at": draft.stop_at.astimezone(timezone.utc).isoformat(),
        })
        self.store.add_audit_event("library.autobook.draft", "created_non_authorizing", {"draft_id": record_id})
        return self._public(next(row for row in self.store.list_library_autobook_drafts() if row["id"] == record_id))

    def list(self) -> dict:
        self._require_protection()
        drafts = [self._public(row) for row in self.store.list_library_autobook_drafts()]
        return {"ok": True, "read_only": True, "booking_authority": False,
                "unattended_submission_enabled": False, "draft_count": len(drafts), "drafts": drafts}

    def revoke(self, draft_id: str) -> dict:
        self._require_protection()
        row = self.store.revoke_library_autobook_draft(draft_id, utc_now().isoformat())
        if row["_changed"]:
            self.store.add_audit_event("library.autobook.draft", "revoked", {"draft_id": draft_id})
        return self._public(row)

    def _public(self, row: dict) -> dict:
        payload = json.loads(self._require_protection().unprotect(bytes(row["encrypted_payload"])).decode())
        return {"id": row["id"], "state": row["state"], "created_at": row["created_at"],
                "updated_at": row["updated_at"], "expires_at": row["expires_at"],
                "exact_target": payload["draft"], "policy_digest": payload["policy_digest"],
                "non_authorizing_acknowledged": True, "booking_authority": False,
                "next_run_at": None, "booking_writes_performed": 0}

    def authorization_preview(self, draft: AutobookPilotDraft) -> dict:
        self._require_protection()
        result = preview_autobook_pilot(draft)
        now = utc_now()
        expires = now + timedelta(minutes=10)
        nonce = secrets.token_hex(16)
        digest = hmac.new(
            self._key,
            ("f4-authorization:" + nonce + draft.model_dump_json() + result["policy_digest"]).encode(),
            hashlib.sha256,
        ).hexdigest()
        with self._lock:
            self._authorization_previews = {
                key: value for key, value in self._authorization_previews.items() if value[1] > now
            }
            self._authorization_previews[digest] = (draft, expires, result["policy_digest"])
        return {
            **result, "phase": "f4_standing_authorization_preview",
            "preview_digest": digest, "preview_expires_at": expires.isoformat(),
            "effect_if_later_enabled": "One automated booking attempt for exactly this room, date, and interval.",
            "requires_fresh_policy_acceptance": True,
            "requires_discussion_room_rules_attestation": True,
            "execution_enabled": False,
        }

    def create_authorization(self, request: AutobookAuthorizationCreateRequest) -> dict:
        protector = self._require_protection()
        with self._lock:
            entry = self._authorization_previews.pop(request.preview_digest, None)
        if entry is None:
            raise ValueError("F4 authorization preview is missing or already consumed; preview again.")
        draft, expires, policy_digest = entry
        if expires <= utc_now():
            raise ValueError("F4 authorization preview expired; preview again.")
        current = preview_autobook_pilot(draft)
        if not hmac.compare_digest(current["policy_digest"], policy_digest):
            raise ValueError("F4 facility policy changed; preview again.")
        now = utc_now()
        authorization_id = str(uuid.uuid4())
        payload = {
            "capability_version": 2,
            "exact_target": draft.model_dump(mode="json"),
            "policy_digest": policy_digest,
            "policy_acceptance_acknowledged": True,
            "discussion_room_rules_acknowledged": True,
            "future_booking_acknowledged": True,
            "maximum_successful_bookings": 1,
            "absolute_expiry": draft.stop_at.isoformat(),
        }
        encrypted = protector.protect(json.dumps(payload, sort_keys=True).encode())
        self.store.create_library_autobook_authorization({
            "id": authorization_id, "encrypted_payload": encrypted,
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
            "execution_at": draft.execution_at.astimezone(timezone.utc).isoformat(),
            "expires_at": draft.stop_at.astimezone(timezone.utc).isoformat(),
        })
        self.store.add_audit_event("library.autobook.authorization", "created_pending_executor",
                                   {"authorization_id": authorization_id})
        return self._public_authorization(next(
            row for row in self.store.list_library_autobook_authorizations()
            if row["id"] == authorization_id
        ))

    def list_authorizations(self) -> dict:
        self._require_protection()
        self._expire_authorizations()
        authorizations = [self._public_authorization(row)
                          for row in self.store.list_library_autobook_authorizations()]
        return {"ok": True, "execution_enabled": False,
                "authorization_count": len(authorizations), "authorizations": authorizations}

    def change_authorization(self, authorization_id: str, action: str) -> dict:
        self._require_protection()
        self._expire_authorizations()
        if action not in {"pause", "revoke"}:
            raise ValueError("Only pause or revoke is available before the F4 executor is enabled.")
        row = self.store.change_library_autobook_authorization_state(
            authorization_id, action, utc_now().isoformat()
        )
        self.store.add_audit_event("library.autobook.authorization", action,
                                   {"authorization_id": authorization_id})
        return self._public_authorization(row)

    def _expire_authorizations(self) -> None:
        for authorization_id in self.store.expire_library_autobook_authorizations(utc_now().isoformat()):
            self.store.add_audit_event("library.autobook.authorization", "expired",
                                       {"authorization_id": authorization_id})

    def _public_authorization(self, row: dict) -> dict:
        payload = json.loads(self._require_protection().unprotect(bytes(row["encrypted_payload"])).decode())
        return {
            "id": row["id"], "state": row["state"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "expires_at": row["expires_at"],
            "exact_target": payload["exact_target"], "policy_digest": payload["policy_digest"],
            "capability_version": payload["capability_version"],
            "maximum_successful_bookings": 1, "attempt_count": row["attempt_count"],
            "success_count": row["success_count"], "execution_enabled": False,
            "next_run_at": None, "booking_writes_performed": "unknown" if row["attempt_count"] else 0,
        }
