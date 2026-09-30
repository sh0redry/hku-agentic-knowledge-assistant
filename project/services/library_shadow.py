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
SHADOW_CAPABILITY_VERSION = 4
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


class ShadowSessionPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def ordered(self):
        if self.end_time <= self.start_time:
            raise ValueError("Each interval must end after it starts, within the target date.")
        return self


class LibraryShadowRuleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facility_type: Literal[
        "single_study_room", "studio_editing_room", "study_table", "study_room",
        "discussion_room",
    ]
    execution_at: datetime
    prepare_at: datetime | None = None
    stop_at: datetime | None = None
    poll_interval_seconds: int = Field(default=15, ge=15, le=120)
    max_date_checks: int = Field(default=1, ge=1, le=20)
    target_date: date
    room_preference_order: list[ShadowRoomPreference] = Field(min_length=1, max_length=30)
    session_preference_order: list[ShadowSessionPreference] = Field(min_length=1, max_length=24)
    allow_room_fallback: bool = False
    allow_time_fallback: bool = False
    eligibility_category: Literal[
        "current_hku_students", "current_hku_staff", "current_hku_space_students",
        "current_hku_space_staff", "hku_alumni",
    ]
    max_runs: Literal[1] = 1
    shadow_only: Literal[True]

    @field_validator("execution_at", "prepare_at", "stop_at", mode="before")
    @classmethod
    def validate_execution(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime):
            raise ValueError("Execution must be a full date and time in Hong Kong time.")
        if value.tzinfo is None:
            value = value.replace(tzinfo=HK_TZ)
        return value.astimezone(HK_TZ)

    @model_validator(mode="after")
    def validate_target(self):
        self.prepare_at = self.prepare_at or self.execution_at
        self.stop_at = self.stop_at or self.execution_at + timedelta(minutes=2)
        if not self.execution_at - timedelta(minutes=10) <= self.prepare_at <= self.execution_at:
            raise ValueError("Preparation must be within 10 minutes before the checking start time.")
        if not self.execution_at < self.stop_at <= self.execution_at + timedelta(minutes=10):
            raise ValueError("Stop time must be after checking starts and within 10 minutes.")
        if not self.execution_at.date() <= self.target_date <= self.execution_at.date() + timedelta(days=14):
            raise ValueError("Target date must be within 14 days of execution; live offered dates remain authoritative.")
        sessions = [(item.start_time, item.end_time) for item in self.session_preference_order]
        if len(set(sessions)) != len(sessions):
            raise ValueError("Preferred intervals must be unique.")
        for start, _end in sessions:
            if datetime.combine(self.target_date, time.fromisoformat(start), HK_TZ) <= self.stop_at:
                raise ValueError("Preferred intervals must start after the stop time.")
        return self

    @field_validator("room_preference_order")
    @classmethod
    def validate_rooms(cls, value: list[ShadowRoomPreference]) -> list[ShadowRoomPreference]:
        keys = [(room.floor.casefold() if room.floor else None, room.room.casefold()) for room in value]
        if len(set(keys)) != len(keys):
            raise ValueError("Room preferences must be unique.")
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
        self._inflight: dict[str, asyncio.Task] = {}
        self._browser_lock = asyncio.Lock()

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
    def _exact_execution(now: datetime, rule: LibraryShadowRuleDefinition) -> tuple[datetime, date]:
        scheduled = rule.prepare_at.astimezone(timezone.utc)
        if scheduled <= now + timedelta(seconds=30):
            raise ValueError("Execution must be at least 30 seconds in the future; it will not roll to tomorrow.")
        if scheduled > now + _MAX_RULE_LIFETIME:
            raise ValueError("Execution must be within 180 days.")
        return scheduled, rule.execution_at.date()

    @staticmethod
    def _choose_target_date(
        offered_dates: list[str], target_date: date,
    ) -> date | None:
        return target_date if target_date.isoformat() in offered_dates else None

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
        next_run, observation_date = self._exact_execution(issued_at, rule)
        expires_at = issued_at + _PREVIEW_TTL
        digest = hmac.new(
            self._preview_key,
            _compact({"request_digest": request_digest, "expires_at": expires_at.isoformat()}),
            hashlib.sha256,
        ).hexdigest()
        self._previews[digest] = ({"rule": normalized, "policy_digest": policy_digest}, expires_at)
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
            "next_scheduled_check_at": rule.execution_at.astimezone(timezone.utc).isoformat(),
            "next_scheduled_check_at_local": rule.execution_at.isoformat(),
            "next_preparation_at": next_run.isoformat(),
            "first_observation_date": observation_date.isoformat(),
            "target_date": rule.target_date.isoformat(),
            "current_hong_kong_time": issued_at.astimezone(HK_TZ).isoformat(),
            "seconds_until_execution": int((rule.execution_at - issued_at).total_seconds()),
            "prepare_at_local": rule.prepare_at.isoformat(),
            "checks_start_at_local": rule.execution_at.isoformat(),
            "stop_at_local": rule.stop_at.isoformat(),
            "maximum_date_checks": rule.max_date_checks,
            "facility_policy_digest": policy_digest,
            "policy_verified_on": self._policy_verified_on(),
            "maximum_scheduled_runs": rule.max_runs,
            "maximum_active_rules": MAX_ACTIVE_SHADOW_RULES,
            "maximum_lifetime_days": int(_MAX_RULE_LIFETIME.total_seconds() // 86400),
            "rule": normalized,
            "warnings": [
                "The scheduled time is an observation time, not a verified HKUL release time.",
                "Preparation only opens and checks the facility page. Complete any login manually. Fresh Date checks start at the specified time, with bounded attempts and a hard deadline; at most one availability Search follows.",
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
        next_run, first_observation_date = self._exact_execution(now, rule)
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
                raise ValueError("This legacy weekday rule must be replaced with a reviewed exact-date rule.")
            if row["state"] != "paused":
                raise ValueError("Only a paused shadow rule can be resumed.")
            if int(row["run_count"]) >= int(row["max_runs"]):
                raise ValueError("This shadow rule has used all scheduled runs.")
            next_state = "active"
            next_run, observation_date = self._exact_execution(
                now, LibraryShadowRuleDefinition.model_validate(payload["rule"]),
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
                "phase": payload.get("phase") if row["outcome"] == "running" else row["outcome"],
                "date_check_count": payload.get("date_check_count", 0),
                "next_check_at": payload.get("next_check_at") if row["outcome"] == "running" else None,
                "last_offered_dates": payload.get("last_offered_dates", []),
                "preparation_completed": payload.get("preparation_completed", False),
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
        running = list(self._inflight.values())
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        self._inflight.clear()

    async def _run_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.run_due_once(background=True)
            except Exception:
                # The scheduler must never take down the web application.
                pass
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=_WAKE_SECONDS)
            except asyncio.TimeoutError:
                continue

    async def run_due_once(self, now: datetime | None = None, *, background: bool = False) -> int:
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
                if row["id"] in self._inflight:
                    continue
                if background:
                    task = asyncio.create_task(self._run_guarded(row, instant))
                    self._inflight[row["id"]] = task
                    task.add_done_callback(lambda _task, key=row["id"]: self._inflight.pop(key, None))
                    continue
                completed += await self._run_guarded(row, instant)
            return completed

    async def _run_guarded(self, row: dict, instant: datetime) -> int:
        try:
            completed = int(await self._run_one(row, instant))
            current = self.store.get_library_shadow_rule(row["id"])
            if current["state"] == "active" and int(current["run_count"]) >= int(current["max_runs"]):
                self.store.set_library_shadow_rule_state(
                    row["id"], "completed", utc_now().isoformat(), next_run_at=None,
                )
            return completed
        except Exception as exc:
            run_ids = self.store.fail_running_library_shadow_runs_for_rule(row["id"], utc_now().isoformat())
            for run_id in run_ids:
                self._audit_run(row["id"], run_id, "internal_error", 0)
            self.store.add_audit_event(
                "library.shadow_run", "library.shadow_run.internal_error",
                {"rule_id": row["id"], "error_type": type(exc).__name__},
            )
            return 0

    def _ensure_window(self, row: dict, rule: LibraryShadowRuleDefinition) -> None:
        if self._stopping.is_set() or self.store.get_library_shadow_rule(row["id"])["state"] != "active":
            raise RuntimeError("RULE_STOPPED_DURING_RUN")
        if utc_now() >= rule.stop_at:
            raise RuntimeError("OBSERVATION_WINDOW_EXPIRED")

    async def _wait_until(self, when: datetime, row: dict, rule: LibraryShadowRuleDefinition) -> None:
        while utc_now() < when:
            self._ensure_window(row, rule)
            await asyncio.sleep(min(1, (when - utc_now()).total_seconds()))
        self._ensure_window(row, rule)

    async def _read(self, capability: str, arguments: dict, row: dict, rule: LibraryShadowRuleDefinition, run_id: str):
        # Waiting rules do not hold this lock. Only live browser reads are serialized.
        async with self._browser_lock:
            self._ensure_window(row, rule)
            saved_policy = self._open(row["encrypted_payload"])["facility_policy_digest"]
            if not hmac.compare_digest(saved_policy, self._policy_digest(self._facility_policy(rule.facility_type))):
                raise RuntimeError("POLICY_CHANGED")
            remaining = (rule.stop_at - utc_now()).total_seconds()
            try:
                result = await asyncio.wait_for(self.tasks.submit_and_wait(
                    capability, arguments, session_id="library-f3-shadow", correlation_id=run_id,
                ), timeout=remaining)
            except asyncio.TimeoutError:
                raise RuntimeError("OBSERVATION_WINDOW_EXPIRED") from None
            self._ensure_window(row, rule)
            return result

    async def _date_options(self, row: dict, rule: LibraryShadowRuleDefinition, run_id: str) -> dict:
        task = await self._read("library.spaces.list_dates", {"facility_type": rule.facility_type}, row, rule, run_id)
        if task.status != TaskStatus.COMPLETED or not task.result:
            raise RuntimeError((task.error or {}).get("code", "DATE_OPTIONS_READ_FAILED"))
        result = task.result
        if not (result.get("read_only") is True
                and result.get("booking_writes_performed") == 0
                and result.get("availability_search_submitted") is False
                and result.get("facility_type") == rule.facility_type
                and result.get("location") == rule.booking_target[0]
                and result.get("booking_facility_type") == rule.booking_target[1]
                and isinstance(result.get("offered_dates"), list)):
            raise RuntimeError("DATE_OPTIONS_INVARIANT_FAILED")
        return result

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
        next_run_text = None
        run_id = str(uuid.uuid4())
        occurrence_key = observation_date.isoformat()
        progress = {
            "target_date": rule.target_date.isoformat(), "observation_date": occurrence_key,
            "candidates": [],
            "suggested_candidate_id": None,
            "availability_slot_count": None,
            "human_feedback": None,
            "error_code": None,
            "facility_policy_digest": current_policy,
            "phase": "preparing", "date_check_count": 0,
            "next_check_at": rule.execution_at.isoformat(),
            "preparation_completed": False, "last_offered_dates": [],
        }
        initial = self._seal(progress)
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
                    "target_date": rule.target_date.isoformat(), "observation_date": occurrence_key, "candidates": [],
                    "suggested_candidate_id": None, "human_feedback": None,
                    "availability_slot_count": None,
                    "error_code": None, "reason": "The app was not awake within the scheduled observation window.",
                }),
                completed_at=now.isoformat(),
            )
            self._audit_run(row["id"], run_id, "missed_after_restart", 0)
            return True

        target_date = rule.target_date
        try:
            if utc_now() < rule.execution_at:
                # Even if preparation already sees the target, never Search before release.
                dates_result = await self._date_options(row, rule, run_id)
                progress.update(preparation_completed=True, phase="waiting_for_start",
                                last_offered_dates=dates_result["offered_dates"])
                self.store.update_library_shadow_progress(run_id, self._seal(progress))
                await self._wait_until(rule.execution_at, row, rule)
            offered = False
            for attempt in range(rule.max_date_checks):
                self._ensure_window(row, rule)
                progress.update(phase="checking_dates", date_check_count=attempt + 1, next_check_at=None)
                self.store.update_library_shadow_progress(run_id, self._seal(progress))
                dates_result = await self._date_options(row, rule, run_id)
                progress["last_offered_dates"] = dates_result["offered_dates"]
                offered = self._choose_target_date(dates_result["offered_dates"], target_date) is not None
                if offered:
                    break
                if attempt + 1 < rule.max_date_checks:
                    next_check = min(utc_now() + timedelta(seconds=rule.poll_interval_seconds), rule.stop_at)
                    progress.update(phase="waiting_for_date", next_check_at=next_check.isoformat())
                    self.store.update_library_shadow_progress(run_id, self._seal(progress))
                    await self._wait_until(next_check, row, rule)
            if not offered:
                self.store.complete_library_shadow_run(
                    run_id, outcome="target_date_not_offered", candidate_count=0,
                    encrypted_payload=self._seal({**progress, "target_date": target_date.isoformat(), "observation_date": occurrence_key,
                                                  "candidates": [], "suggested_candidate_id": None,
                                                  "availability_slot_count": None, "human_feedback": None,
                                                  "error_code": None, "booking_writes_performed": 0}),
                    completed_at=utc_now().isoformat(),
                )
                self._audit_run(row["id"], run_id, "target_date_not_offered", 0)
                return True
            progress.update(phase="searching_availability", next_check_at=None)
            self.store.update_library_shadow_progress(run_id, self._seal(progress))
            completed = await self._read(
                "library.spaces.search_availability",
                {"facility_type": rule.facility_type, "date": target_date.isoformat()},
                row, rule, run_id,
            )
        except Exception as exc:
            code = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            outcome = "authentication_required" if code in {
                "BROWSER_NOT_CONNECTED", "BROWSER_DISCONNECTED", "BROWSER_TIMEOUT",
                "PORTAL_LOGIN_REQUIRED", "SSO_MANUAL_ACTION_REQUIRED", "LIBRARY_LOGIN_REQUIRED",
            } else "read_failed"
            outcome = {"RULE_STOPPED_DURING_RUN": "rule_stopped_during_run",
                       "OBSERVATION_WINDOW_EXPIRED": "observation_window_expired",
                       "POLICY_CHANGED": "policy_changed"}.get(code, outcome)
            if code == "POLICY_CHANGED":
                self.store.set_library_shadow_rule_state(row["id"], "policy_changed", utc_now().isoformat(), next_run_at=None)
            self.store.complete_library_shadow_run(
                run_id,
                outcome=outcome,
                candidate_count=0,
                encrypted_payload=self._seal({
                    **progress,
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
            **progress,
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
        if current_rule["state"] == "active" and int(current_rule["run_count"]) >= int(current_rule["max_runs"]):
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
        now: datetime | None = None,
    ) -> list[dict]:
        rooms = rule.room_preference_order
        starts = rule.session_preference_order
        instant = now or utc_now()
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
            try:
                starts_at = datetime.combine(date.fromisoformat(target_date), time.fromisoformat(start), HK_TZ)
            except ValueError:
                continue
            if starts_at <= instant:
                continue
            room_index = next((index for index, preferred in enumerate(allowed_rooms)
                               if preferred.room.casefold() == room_name.casefold()
                               and (preferred.floor is None or preferred.floor.casefold() == floor_name.casefold())), None)
            time_index = next((index for index, preferred in enumerate(allowed_starts)
                               if preferred.start_time == start and preferred.end_time == slot.get("end_time")), None)
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
