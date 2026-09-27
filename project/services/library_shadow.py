from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agents.models import TaskStatus, utc_now
from services.data_protection import DataProtectionUnavailable, WindowsUserDataProtector
from services.store import SQLiteStore


HK_TZ = ZoneInfo("Asia/Hong_Kong")
SHADOW_CAPABILITY_VERSION = 2
MAX_ACTIVE_SHADOW_RULES = 5
SHADOW_FACILITY_TYPES = {
    "single_study_room", "studio_editing_room", "study_table", "study_room",
    "discussion_room",
}
ELIGIBILITY_CATEGORIES = {
    "current_hku_students", "current_hku_staff", "current_hku_space_students",
    "current_hku_space_staff", "hku_alumni",
}
_PREVIEW_TTL = timedelta(minutes=10)
_MAX_RULE_LIFETIME = timedelta(days=180)
_MISSED_GRACE = timedelta(minutes=2)
_WAKE_SECONDS = 10


class ShadowRoomPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    floor: str | None = Field(default=None, min_length=1, max_length=80)
    room: str = Field(min_length=1, max_length=200)

    @field_validator("floor", "room")
    @classmethod
    def normalize_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Room and floor preferences must not be empty.")
        return normalized


class LibraryShadowRuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_type: Literal[
        "single_study_room", "studio_editing_room", "study_table", "study_room",
        "discussion_room",
    ]
    target_weekdays: list[int] = Field(min_length=1, max_length=7)
    run_time_local: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    room_preference_order: list[ShadowRoomPreference] = Field(min_length=1, max_length=30)
    start_time_preference_order: list[str] = Field(min_length=1, max_length=24)
    allow_room_fallback: bool = False
    allow_time_fallback: bool = False
    eligibility_category: Literal[
        "current_hku_students", "current_hku_staff", "current_hku_space_students",
        "current_hku_space_staff", "hku_alumni",
    ]
    max_runs: int = Field(default=20, ge=1, le=20)
    shadow_only: Literal[True]

    @field_validator("target_weekdays")
    @classmethod
    def validate_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 0 or day > 6 for day in value) or len(set(value)) != len(value):
            raise ValueError("Weekdays must be unique ISO weekdays encoded 0=Monday through 6=Sunday.")
        return value

    @field_validator("room_preference_order")
    @classmethod
    def validate_rooms(cls, value: list[ShadowRoomPreference]) -> list[ShadowRoomPreference]:
        keys = [(room.floor.casefold() if room.floor else None, room.room.casefold()) for room in value]
        if len(set(keys)) != len(keys):
            raise ValueError("Room preferences must be unique.")
        return value

    @field_validator("start_time_preference_order")
    @classmethod
    def validate_start_times(cls, value: list[str]) -> list[str]:
        if any(not time_text or len(time_text) != 5 or time_text[2] != ":" for time_text in value):
            raise ValueError("Start-time preferences must use exact HH:MM values.")
        try:
            for time_text in value:
                time.fromisoformat(time_text)
        except ValueError as exc:
            raise ValueError("Start-time preferences must use valid 24-hour HH:MM values.") from exc
        if len(set(value)) != len(value):
            raise ValueError("Start-time preferences must be unique.")
        return value

    @property
    def booking_target(self) -> tuple[str, str]:
        if self.facility_type == "study_room":
            return ("Chi Wah Learning Commons", "Study Room")
        labels = {
            "single_study_room": ("Main Library", "Single Study Room (3 sessions)"),
            "studio_editing_room": ("Main Library", "Studio and Editing Room"),
            "study_table": ("Main Library", "Study Table"),
            "discussion_room": ("Main Library", "Discussion Room"),
        }
        return labels[self.facility_type]


class ShadowPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: LibraryShadowRuleDefinition


class ShadowCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    shadow_only_acknowledged: Literal[True]


class ShadowRuleActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revoke_acknowledged: bool = False


class ShadowFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str | None = Field(default=None, min_length=1, max_length=64)
    no_slot_would_be_booked: bool = False

    @model_validator(mode="after")
    def require_one_feedback_choice(self):
        if (self.candidate_id is None) == (self.no_slot_would_be_booked is False):
            raise ValueError("Choose exactly one candidate, or confirm that you would book none.")
        return self


def _compact(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class LibraryShadowScheduler:
    """Persistent, encrypted, read-only F3 scheduler. It has no booking executor."""

    def __init__(self, store: SQLiteStore, tasks):
        self.store = store
        self.tasks = tasks
        self._previews: dict[str, tuple[dict, datetime]] = {}
        self._preview_key = secrets.token_bytes(32)
        try:
            self._protector = WindowsUserDataProtector()
            self.protection_error = None
        except DataProtectionUnavailable as exc:
            self._protector = None
            self.protection_error = str(exc)
        self._worker: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._tick_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._protector is not None

    @property
    def running(self) -> bool:
        return self._worker is not None and not self._worker.done()

    def _seal(self, value: dict) -> bytes:
        if self._protector is None:
            raise DataProtectionUnavailable(self.protection_error or "F3 data protection is unavailable.")
        return self._protector.protect(_compact(value))

    def _open(self, value: bytes) -> dict:
        if self._protector is None:
            raise DataProtectionUnavailable(self.protection_error or "F3 data protection is unavailable.")
        return json.loads(self._protector.unprotect(bytes(value)).decode("utf-8"))

    @staticmethod
    def _facility_policy(facility_type: str) -> dict:
        from agents.library.agent import LibraryFacilityListCapability

        facility = next(
            (item for item in LibraryFacilityListCapability.FACILITIES
             if item["facility_type"] == facility_type),
            None,
        )
        if facility is None or facility_type not in SHADOW_FACILITY_TYPES:
            raise ValueError("F3 supports only facility types with an existing F1 preview policy.")
        return facility

    @staticmethod
    def _policy_digest(facility: dict) -> str:
        from agents.library.agent import LibrarySpaceBookingPreviewCapability

        return hashlib.sha256(_compact({
            "capability_version": SHADOW_CAPABILITY_VERSION,
            "policy_verified_on": LibrarySpaceBookingPreviewCapability.POLICY_VERIFIED_ON,
            "policy_sources": LibrarySpaceBookingPreviewCapability.POLICY_SOURCES,
            "facility": facility,
        })).hexdigest()

    @staticmethod
    def _policy_verified_on() -> str:
        from agents.library.agent import LibrarySpaceBookingPreviewCapability

        return LibrarySpaceBookingPreviewCapability.POLICY_VERIFIED_ON

    @staticmethod
    def _next_occurrence(
        now: datetime, target_weekdays: list[int], run_time_local: str,
        after_target_date: date | None = None,
    ) -> tuple[datetime, date]:
        local_now = now.astimezone(HK_TZ)
        run_time = time.fromisoformat(run_time_local)
        cursor = after_target_date + timedelta(days=1) if after_target_date else local_now.date()
        for offset in range(0, 370):
            observation_date = cursor + timedelta(days=offset)
            scheduled = datetime.combine(observation_date, run_time, HK_TZ)
            if scheduled > local_now + timedelta(seconds=30):
                return scheduled.astimezone(timezone.utc), observation_date
        raise ValueError("No daily observation was found in the next year.")

    @staticmethod
    def _choose_target_date(
        offered_dates: list[str], observation_date: date,
        target_weekdays: list[int], observed_targets: set[str],
    ) -> date | None:
        offered = sorted(date.fromisoformat(item) for item in offered_dates)
        return next((item for item in offered
                     if item >= observation_date and item.weekday() in target_weekdays
                     and item.isoformat() not in observed_targets), None)

    def preview(self, request: ShadowPreviewRequest) -> dict:
        rule = request.rule
        if not self.enabled:
            raise DataProtectionUnavailable(self.protection_error or "F3 data protection is unavailable.")
        if len(self.store.list_active_library_shadow_rules()) >= MAX_ACTIVE_SHADOW_RULES:
            raise ValueError("Pause or revoke an active F3 rule before preparing another rule.")
        facility = self._facility_policy(rule.facility_type)
        if rule.eligibility_category not in facility.get("eligibility", []):
            raise ValueError("The declared eligibility category is not listed for this facility type.")
        policy_digest = self._policy_digest(facility)
        normalized = rule.model_dump(mode="json")
        request_digest = hashlib.sha256(_compact({"rule": normalized, "policy_digest": policy_digest})).hexdigest()
        issued_at = utc_now()
        expires_at = issued_at + _PREVIEW_TTL
        digest = hmac.new(
            self._preview_key,
            _compact({"request_digest": request_digest, "expires_at": expires_at.isoformat()}),
            hashlib.sha256,
        ).hexdigest()
        self._previews[digest] = ({"rule": normalized, "policy_digest": policy_digest}, expires_at)
        next_run, observation_date = self._next_occurrence(
            issued_at, rule.target_weekdays, rule.run_time_local,
        )
        return {
            "ok": True,
            "read_only": True,
            "shadow_only": True,
            "future_booking_authority_created": False,
            "booking_writes_performed": 0,
            "library_writes_performed": 0,
            "browser_interactions_performed": False,
            "rule_preview_digest": digest,
            "preview_expires_at": expires_at.isoformat(),
            "next_scheduled_check_at": next_run.isoformat(),
            "next_scheduled_check_at_local": next_run.astimezone(HK_TZ).isoformat(),
            "first_observation_date": observation_date.isoformat(),
            "target_date": None,
            "facility_policy_digest": policy_digest,
            "policy_verified_on": self._policy_verified_on(),
            "maximum_scheduled_runs": rule.max_runs,
            "maximum_active_rules": MAX_ACTIVE_SHADOW_RULES,
            "maximum_lifetime_days": int(_MAX_RULE_LIFETIME.total_seconds() // 86400),
            "rule": normalized,
            "warnings": [
                "The scheduled time is an observation time, not a verified HKUL release time.",
                "Each daily observation reads this facility's live Date options and performs at most one read-only availability Search for an offered matching weekday.",
                "F3 output is a suggestion only; it cannot submit, reserve, cancel, or authorize an HKUL booking.",
                "Eligibility remains user-declared and is not verified against the HKUL account.",
                "Policy-change detection compares the local verified policy catalog; F3 does not poll HKUL policy pages.",
            ],
        }

    def create_rule(self, request: ShadowCreateRequest) -> dict:
        if not self.enabled:
            raise DataProtectionUnavailable(self.protection_error or "F3 data protection is unavailable.")
        issued = self._previews.pop(request.preview_digest, None)
        if issued is None:
            raise ValueError("The F3 rule preview was not issued by this running process.")
        payload, expires_at = issued
        if expires_at <= utc_now():
            raise ValueError("The F3 rule preview expired; create and review a fresh one.")
        rule = LibraryShadowRuleDefinition.model_validate(payload["rule"])
        facility = self._facility_policy(rule.facility_type)
        if rule.eligibility_category not in facility.get("eligibility", []):
            raise ValueError("The declared eligibility category is not listed for this facility type.")
        current_policy_digest = self._policy_digest(facility)
        if not hmac.compare_digest(current_policy_digest, payload["policy_digest"]):
            raise ValueError("The facility policy changed after preview; review a fresh preview.")
        now = utc_now()
        next_run, first_observation_date = self._next_occurrence(now, rule.target_weekdays, rule.run_time_local)
        rule_id = str(uuid.uuid4())
        stored = {
            "rule": rule.model_dump(mode="json"),
            "facility_policy_digest": current_policy_digest,
            "created_by": "loopback_local_gui",
            "created_at": now.isoformat(),
            "first_observation_date": first_observation_date.isoformat(),
            "shadow_only": True,
            "booking_executor_capability": None,
        }
        expires_at_rule = now + _MAX_RULE_LIFETIME
        self.store.create_library_shadow_rule({
            "id": rule_id,
            "state": "active",
            "encrypted_payload": self._seal(stored),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "next_run_at": next_run.isoformat(),
            "expires_at": expires_at_rule.isoformat(),
            "max_runs": rule.max_runs,
            "version": SHADOW_CAPABILITY_VERSION,
        }, max_active=MAX_ACTIVE_SHADOW_RULES)
        self.store.add_audit_event(
            "library.shadow_rule",
            "library.shadow_rule.created",
            {"rule_id": rule_id, "shadow_only": True, "max_runs": rule.max_runs},
        )
        return self._public_rule(self.store.get_library_shadow_rule(rule_id), include_private=True)

    def _public_rule(self, row: dict, include_private: bool = False) -> dict:
        payload = self._open(row["encrypted_payload"])
        result = {
            "id": row["id"],
            "state": row["state"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "next_run_at": row["next_run_at"],
            "expires_at": row["expires_at"],
            "run_count": row["run_count"],
            "max_runs": row["max_runs"],
            "shadow_only": True,
            "booking_authority": False,
        }
        if include_private:
            result["rule"] = payload["rule"]
            result["facility_policy_digest"] = payload["facility_policy_digest"]
        return result

    def list_rules(self) -> dict:
        rows = self.store.list_library_shadow_rules()
        rules = [self._public_rule(row, include_private=True) for row in rows]
        return {
            "shadow_only": True,
            "booking_authority": False,
            "rule_count": len(rules),
            "rules": rules,
            "data_protection": "windows_current_user_dpapi" if self.enabled else "unavailable",
        }

    def change_rule_state(self, rule_id: str, action: Literal["pause", "resume", "revoke"]) -> dict:
        row = self.store.get_library_shadow_rule(rule_id)
        payload = self._open(row["encrypted_payload"])
        now = utc_now()
        if action == "pause":
            next_state, next_run = "paused", None
        elif action == "resume":
            if int(row["version"]) < SHADOW_CAPABILITY_VERSION:
                raise ValueError("This version-1 rule uses the old schedule; create a fresh version-2 rule instead.")
            if row["state"] != "paused":
                raise ValueError("Only a paused shadow rule can be resumed.")
            if int(row["run_count"]) >= int(row["max_runs"]):
                raise ValueError("This shadow rule has used all scheduled runs.")
            next_state = "active"
            next_run, observation_date = self._next_occurrence(
                now, payload["rule"]["target_weekdays"], payload["rule"]["run_time_local"],
            )
            payload["next_observation_date"] = observation_date.isoformat()
        else:
            next_state, next_run = "revoked", None
            payload["revoked_at"] = now.isoformat()
        payload["state"] = next_state
        updated = self.store.set_library_shadow_rule_state(
            rule_id, next_state, now.isoformat(), self._seal(payload),
            next_run_at=next_run,
        )
        self.store.add_audit_event(
            "library.shadow_rule",
            {
                "pause": "library.shadow_rule.paused",
                "resume": "library.shadow_rule.resumed",
                "revoke": "library.shadow_rule.revoked",
            }[action],
            {"rule_id": rule_id, "state": next_state},
        )
        return self._public_rule(updated, include_private=True)

    def _public_run(self, row: dict, include_private: bool = True) -> dict:
        payload = self._open(row["encrypted_payload"])
        scheduled_at = _parse_iso(row["scheduled_at"])
        result = {
            "id": row["id"],
            "rule_id": row["rule_id"],
            "scheduled_at": row["scheduled_at"],
            "scheduled_at_local": scheduled_at.astimezone(HK_TZ).isoformat() if scheduled_at else None,
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "outcome": row["outcome"],
            "candidate_count": row["candidate_count"],
            "feedback_state": row["feedback_state"],
            "choice_agreement": None if row["choice_agreement"] is None else bool(row["choice_agreement"]),
        }
        if include_private:
            result.update({
                "target_date": payload.get("target_date"),
                "candidates": payload.get("candidates", []),
                "suggested_candidate_id": payload.get("suggested_candidate_id"),
                "availability_slot_count": payload.get("availability_slot_count"),
                "suggestion_reason": payload.get("suggestion_reason"),
                "error_code": payload.get("error_code"),
                "human_feedback": payload.get("human_feedback"),
                "read_only": True,
                "booking_writes_performed": 0,
                "slot_selection_performed": False,
                "booking_form_opened": False,
            })
        return result

    def list_runs(self, rule_id: str | None = None, limit: int = 100) -> dict:
        rows = self.store.list_library_shadow_runs(rule_id=rule_id, limit=limit)
        runs = [self._public_run(row) for row in rows]
        reviewed = [run for run in runs if run["choice_agreement"] is not None]
        return {
            "shadow_only": True,
            "run_count": len(runs),
            "reviewed_run_count": len(reviewed),
            "exact_choice_agreement_count": sum(run["choice_agreement"] is True for run in reviewed),
            "exact_choice_agreement_rate": (
                round(sum(run["choice_agreement"] is True for run in reviewed) / len(reviewed), 4)
                if reviewed else None
            ),
            "runs": runs,
        }

    def record_feedback(self, run_id: str, request: ShadowFeedbackRequest) -> dict:
        row = self.store.get_library_shadow_run(run_id)
        if row["outcome"] not in {"suggestion_ready", "no_match"}:
            raise ValueError("Only a completed shadow suggestion or no-match run can be compared.")
        payload = self._open(row["encrypted_payload"])
        candidates = payload.get("candidates", [])
        if request.no_slot_would_be_booked:
            if row["outcome"] != "no_match":
                # The user may reject every suggested candidate; this is a valid disagreement.
                candidate_id = None
            else:
                candidate_id = None
        else:
            if not any(item.get("candidate_id") == request.candidate_id for item in candidates):
                raise ValueError("The selected candidate does not belong to this run.")
            candidate_id = request.candidate_id
        agreement = candidate_id == payload.get("suggested_candidate_id")
        payload["human_feedback"] = {
            "candidate_id": candidate_id,
            "no_slot_would_be_booked": request.no_slot_would_be_booked,
            "recorded_at": utc_now().isoformat(),
        }
        updated = self.store.update_library_shadow_run_feedback(
            run_id,
            encrypted_payload=self._seal(payload),
            feedback_state="reviewed",
            choice_agreement=agreement,
        )
        self.store.add_audit_event(
            "library.shadow_run",
            "library.shadow_run.feedback_recorded",
            {"run_id": run_id, "choice_agreement": agreement},
        )
        return self._public_run(updated)

    async def start(self) -> None:
        if not self.enabled or self._worker is not None:
            return
        now = utc_now().isoformat()
        for row in self.store.list_library_shadow_rules():
            if int(row["version"]) < SHADOW_CAPABILITY_VERSION and row["state"] in {"active", "paused"}:
                self.store.set_library_shadow_rule_state(row["id"], "migration_required", now, next_run_at=None)
                self.store.add_audit_event("library.shadow_rule", "library.shadow_rule.migration_required", {"rule_id": row["id"]})
        try:
            for row in self.store.list_active_library_shadow_rules():
                self._open(row["encrypted_payload"])
        except Exception:
            self._protector = None
            self.protection_error = (
                "Existing F3 rule data could not be opened by the current Windows user; "
                "the scheduler remains disabled."
            )
            return
        interrupted = self.store.mark_interrupted_library_shadow_runs(now)
        for row in interrupted:
            self.store.add_audit_event(
                "library.shadow_run",
                "library.shadow_run.interrupted_after_restart",
                {"run_id": row["id"], "rule_id": row["rule_id"]},
            )
        for rule_id in self.store.complete_exhausted_library_shadow_rules(now):
            self.store.add_audit_event(
                "library.shadow_rule",
                "library.shadow_rule.completed_after_restart",
                {"rule_id": rule_id, "reason": "max_runs_reached"},
            )
        for rule_id in self.store.expire_library_shadow_rules(now):
            self.store.add_audit_event(
                "library.shadow_rule",
                "library.shadow_rule.expired",
                {"rule_id": rule_id},
            )
        self._stopping.clear()
        self._worker = asyncio.create_task(self._run_loop(), name="library-shadow-scheduler")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._stopping.set()
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        self._worker = None

    async def _run_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.run_due_once()
            except Exception:
                # The scheduler must never take down the web application.
                pass
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=_WAKE_SECONDS)
            except asyncio.TimeoutError:
                continue

    async def run_due_once(self, now: datetime | None = None) -> int:
        if not self.enabled:
            return 0
        if self._tick_lock.locked():
            return 0
        async with self._tick_lock:
            instant = (now or utc_now()).astimezone(timezone.utc)
            now_text = instant.isoformat()
            for rule_id in self.store.expire_library_shadow_rules(now_text):
                self.store.add_audit_event(
                    "library.shadow_rule", "library.shadow_rule.expired",
                    {"rule_id": rule_id},
                )
            due = self.store.list_due_library_shadow_rules(now_text, limit=20)
            completed = 0
            for row in due:
                try:
                    if await self._run_one(row, instant):
                        completed += 1
                    current = self.store.get_library_shadow_rule(row["id"])
                    if current["state"] == "active" and int(current["run_count"]) >= int(current["max_runs"]):
                        self.store.set_library_shadow_rule_state(
                            row["id"], "completed", utc_now().isoformat(), next_run_at=None,
                        )
                except Exception as exc:
                    run_ids = self.store.fail_running_library_shadow_runs_for_rule(
                        row["id"], utc_now().isoformat(),
                    )
                    for run_id in run_ids:
                        self._audit_run(row["id"], run_id, "internal_error", 0)
                    self.store.add_audit_event(
                        "library.shadow_run",
                        "library.shadow_run.internal_error",
                        {"rule_id": row["id"], "error_type": type(exc).__name__},
                    )
            return completed

    async def _run_one(self, row: dict, now: datetime) -> bool:
        if int(row["version"]) < SHADOW_CAPABILITY_VERSION:
            self.store.set_library_shadow_rule_state(row["id"], "migration_required", now.isoformat(), next_run_at=None)
            return False
        rule_payload = self._open(row["encrypted_payload"])
        rule = LibraryShadowRuleDefinition.model_validate(rule_payload["rule"])
        current_policy = self._policy_digest(self._facility_policy(rule.facility_type))
        if not hmac.compare_digest(current_policy, rule_payload["facility_policy_digest"]):
            payload = {**rule_payload, "state": "policy_changed", "policy_changed_at": now.isoformat()}
            self.store.set_library_shadow_rule_state(
                row["id"], "policy_changed", now.isoformat(), self._seal(payload),
                next_run_at=None,
            )
            self.store.add_audit_event(
                "library.shadow_rule", "library.shadow_rule.policy_changed",
                {"rule_id": row["id"]},
            )
            return False

        scheduled_at = _parse_iso(row["next_run_at"])
        if scheduled_at is None:
            return False
        local_scheduled = scheduled_at.astimezone(HK_TZ)
        observation_date = local_scheduled.date()
        next_run, _next_date = self._next_occurrence(
            now, rule.target_weekdays, rule.run_time_local, after_target_date=observation_date,
        )
        if int(row["run_count"]) + 1 >= int(row["max_runs"]):
            next_run_text = None
        else:
            next_run_text = next_run.isoformat()
        run_id = str(uuid.uuid4())
        occurrence_key = observation_date.isoformat()
        initial = self._seal({
            "target_date": None, "observation_date": occurrence_key,
            "candidates": [],
            "suggested_candidate_id": None,
            "availability_slot_count": None,
            "human_feedback": None,
            "error_code": None,
            "facility_policy_digest": current_policy,
        })
        claimed = self.store.claim_library_shadow_occurrence(
            rule_id=row["id"], run_id=run_id, occurrence_key=occurrence_key,
            scheduled_at=scheduled_at.isoformat(), next_run_at=next_run_text,
            started_at=now.isoformat(), encrypted_payload=initial,
        )
        if not claimed:
            return False

        if now - scheduled_at > _MISSED_GRACE:
            self.store.complete_library_shadow_run(
                run_id,
                outcome="missed_after_restart",
                candidate_count=0,
                encrypted_payload=self._seal({
                    "target_date": None, "observation_date": occurrence_key, "candidates": [],
                    "suggested_candidate_id": None, "human_feedback": None,
                    "availability_slot_count": None,
                    "error_code": None, "reason": "The app was not awake within the scheduled observation window.",
                }),
                completed_at=now.isoformat(),
            )
            self._audit_run(row["id"], run_id, "missed_after_restart", 0)
            return True

        target_date = None
        try:
            dates_task = await self.tasks.submit_and_wait(
                "library.spaces.list_dates", {"facility_type": rule.facility_type},
                session_id="library-f3-shadow", correlation_id=run_id,
            )
            if dates_task.status != TaskStatus.COMPLETED or not dates_task.result:
                raise RuntimeError((dates_task.error or {}).get("code", "DATE_OPTIONS_READ_FAILED"))
            dates_result = dates_task.result
            if not (dates_result.get("read_only") is True
                    and dates_result.get("booking_writes_performed") == 0
                    and dates_result.get("availability_search_submitted") is False
                    and dates_result.get("facility_type") == rule.facility_type
                    and dates_result.get("location") == rule.booking_target[0]
                    and dates_result.get("booking_facility_type") == rule.booking_target[1]):
                raise RuntimeError("DATE_OPTIONS_INVARIANT_FAILED")
            prior_runs = self.store.list_library_shadow_runs(rule_id=row["id"], limit=100)
            observed_targets = {self._open(item["encrypted_payload"]).get("target_date")
                                for item in prior_runs if item["id"] != run_id}
            target_date = self._choose_target_date(
                dates_result["offered_dates"], observation_date,
                rule.target_weekdays, observed_targets,
            )
            if target_date is None:
                self.store.complete_library_shadow_run(
                    run_id, outcome="target_date_not_offered", candidate_count=0,
                    encrypted_payload=self._seal({"target_date": None, "observation_date": occurrence_key,
                                                  "candidates": [], "suggested_candidate_id": None,
                                                  "availability_slot_count": None, "human_feedback": None,
                                                  "error_code": None, "booking_writes_performed": 0}),
                    completed_at=utc_now().isoformat(),
                )
                self._audit_run(row["id"], run_id, "target_date_not_offered", 0)
                return True
            completed = await self.tasks.submit_and_wait(
                "library.spaces.search_availability",
                {"facility_type": rule.facility_type, "date": target_date.isoformat()},
                session_id="library-f3-shadow", correlation_id=run_id,
            )
        except Exception as exc:
            code = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            outcome = "authentication_required" if code in {
                "BROWSER_NOT_CONNECTED", "BROWSER_DISCONNECTED", "BROWSER_TIMEOUT",
                "PORTAL_LOGIN_REQUIRED", "SSO_MANUAL_ACTION_REQUIRED", "LIBRARY_LOGIN_REQUIRED",
            } else "read_failed"
            self.store.complete_library_shadow_run(
                run_id,
                outcome=outcome,
                candidate_count=0,
                encrypted_payload=self._seal({
                    "target_date": target_date.isoformat() if target_date else None,
                    "observation_date": occurrence_key,
                    "candidates": [],
                    "suggested_candidate_id": None,
                    "availability_slot_count": None,
                    "human_feedback": None,
                    "error_code": code,
                    "facility_policy_digest": current_policy,
                    "read_only": True,
                    "booking_writes_performed": 0,
                }),
                completed_at=utc_now().isoformat(),
            )
            self._audit_run(row["id"], run_id, outcome, 0)
            return True
        current_rule = self.store.get_library_shadow_rule(row["id"])
        if current_rule["state"] != "active":
            outcome, candidates, chosen, error_code = "rule_stopped_during_run", [], None, None
            availability_slot_count = None
        elif completed.status != TaskStatus.COMPLETED or not completed.result:
            code = (completed.error or {}).get("code", "READ_FAILED")
            outcome = "authentication_required" if code in {
                "BROWSER_NOT_CONNECTED", "BROWSER_DISCONNECTED", "BROWSER_TIMEOUT",
                "PORTAL_LOGIN_REQUIRED", "SSO_MANUAL_ACTION_REQUIRED", "LIBRARY_LOGIN_REQUIRED",
            } else "read_failed"
            candidates, chosen, error_code = [], None, code
            availability_slot_count = None
        else:
            result = completed.result
            available_slots = result.get("available_slots") or []
            diagnostics = result.get("diagnostics") or {}
            valid_read = (
                result.get("read_only") is True
                and result.get("booking_writes_performed") == 0
                and result.get("library_writes_performed") == 0
                and result.get("domain_writes_performed") == 0
                and result.get("data_reads_performed") == 1
                and result.get("slot_selection_performed") is False
                and result.get("booking_form_opened") is False
                and result.get("result_set_complete") is True
                and result.get("date") == target_date.isoformat()
                and result.get("facility_type") == rule.facility_type
                and result.get("location") == rule.booking_target[0]
                and result.get("booking_facility_type") == rule.booking_target[1]
                and result.get("available_slot_count") == len(available_slots)
                and diagnostics.get("availability_marker_found") is True
                and diagnostics.get("availability_legend_found") is True
                and diagnostics.get("booked_legend_found") is True
                and diagnostics.get("table_matrix_found") is True
                and diagnostics.get("selected_filters_found") is True
                and diagnostics.get("result_set_complete") is True
                and diagnostics.get("unclassified_status_cell_count") == 0
            )
            if not valid_read:
                outcome, candidates, chosen, error_code = "unverified_read", [], None, "SHADOW_READ_INVARIANT_FAILED"
                availability_slot_count = None
            else:
                availability_slot_count = len(available_slots)
                candidates = self._rank_candidates(
                    rule, available_slots, row["id"], target_date.isoformat(),
                )
                chosen = candidates[0]["candidate_id"] if candidates else None
                outcome = "suggestion_ready" if candidates else "no_match"
                error_code = None

        final_payload = {
            "target_date": target_date.isoformat(),
            "observation_date": occurrence_key,
            "candidates": candidates,
            "suggested_candidate_id": chosen,
            "availability_slot_count": availability_slot_count,
            "suggestion_reason": (
                "ranked_candidate_available" if chosen else
                "no_available_slots" if availability_slot_count == 0 else
                "no_slot_matched_preferences" if availability_slot_count is not None else None
            ),
            "human_feedback": None,
            "error_code": error_code,
            "facility_policy_digest": current_policy,
            "read_only": True,
            "booking_writes_performed": 0,
        }
        self.store.complete_library_shadow_run(
            run_id,
            outcome=outcome,
            candidate_count=len(candidates),
            encrypted_payload=self._seal(final_payload),
            completed_at=utc_now().isoformat(),
        )
        self._audit_run(row["id"], run_id, outcome, len(candidates))
        if int(current_rule["run_count"]) >= int(current_rule["max_runs"]):
            try:
                self.store.set_library_shadow_rule_state(
                    row["id"], "completed", utc_now().isoformat(), next_run_at=None,
                )
            except ValueError:
                pass
        return True

    @staticmethod
    def _rank_candidates(
        rule: LibraryShadowRuleDefinition,
        slots: list[dict],
        rule_id: str,
        target_date: str,
    ) -> list[dict]:
        rooms = rule.room_preference_order
        starts = rule.start_time_preference_order
        allowed_rooms = rooms if rule.allow_room_fallback else rooms[:1]
        allowed_starts = starts if rule.allow_time_fallback else starts[:1]
        candidates = []
        seen_slots: set[tuple[str, str, str, str]] = set()
        for slot in slots:
            room_name = " ".join(str(slot.get("room", "")).split())
            floor_name = " ".join(str(slot.get("floor", "")).split())
            start = str(slot.get("start_time", ""))
            if slot.get("status") != "available":
                continue
            room_index = next((index for index, preferred in enumerate(allowed_rooms)
                               if preferred.room.casefold() == room_name.casefold()
                               and (preferred.floor is None or preferred.floor.casefold() == floor_name.casefold())), None)
            time_index = next((index for index, preferred in enumerate(allowed_starts)
                               if preferred == start), None)
            if room_index is None or time_index is None:
                continue
            slot_key = (
                floor_name.casefold(), room_name.casefold(), start,
                str(slot.get("end_time", "")),
            )
            if slot_key in seen_slots:
                continue
            seen_slots.add(slot_key)
            candidate_id = hashlib.sha256(_compact({
                "rule_id": rule_id,
                "target_date": target_date,
                "slot": slot_key,
            })).hexdigest()[:24]
            candidates.append({
                "candidate_id": candidate_id,
                "floor": floor_name or None,
                "room": room_name,
                "start_time": start,
                "end_time": slot.get("end_time"),
                "room_preference_rank": room_index,
                "time_preference_rank": time_index,
            })
        candidates.sort(key=lambda item: (
            item["room_preference_rank"], item["time_preference_rank"],
            item["start_time"], item["room"].casefold(),
        ))
        return candidates[:100]

    def _audit_run(self, rule_id: str, run_id: str, outcome: str, candidate_count: int) -> None:
        self.store.add_audit_event(
            "library.shadow_run",
            "library.shadow_run.completed",
            {
                "rule_id": rule_id,
                "run_id": run_id,
                "outcome": outcome,
                "candidate_count": candidate_count,
                "booking_writes_performed": 0,
            },
        )
