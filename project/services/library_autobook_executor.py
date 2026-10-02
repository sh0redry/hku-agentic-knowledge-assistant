"""Local, explicitly armed, one-shot F4 pilot. Never registered as a Chat tool."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import timedelta, timezone

from agents.models import TaskStatus, utc_now
from agents.library.agent import library_booking_host_is_loopback, LibrarySpaceBookingPreviewCapability
from services.library_autobook import AutobookPilotDraft
from services.library_shadow import HK_TZ, LibraryShadowScheduler


class F4Refusal(Exception):
    def __init__(self, code):
        self.code = code


class LibraryAutobookExecutor:
    """Separate runtime opt-in; old authorizations do not acquire authority on upgrade.

    Runtime enablement is process-only. Exact arming is durable; a restart needs
    runtime enablement again and never replays an interrupted occurrence.
    """

    def __init__(self, drafts, tasks, connector, browser_lock=None):
        self.drafts, self.store, self.tasks, self.connector = drafts, drafts.store, tasks, connector
        self.enabled = False
        self.dry_run = True
        self._worker = None
        self._inflight = {}
        self._tick_lock = asyncio.Lock()
        self._browser_lock = browser_lock or asyncio.Lock()
        self._stopping = False

    def status(self):
        return {"execution_enabled": self.enabled, "dry_run": self.dry_run,
                "scheduler_running": self._worker is not None and not self._worker.done(),
                "pilot_scope": "discussion_room_empty_target_day_only", "maximum_successful_bookings": 1,
                "eligibility_basis": "self_declared_not_account_verified"}

    def configure(self, *, enabled: bool, dry_run: bool):
        if not library_booking_host_is_loopback():
            raise ValueError("F4 requires loopback binding.")
        self.drafts._require_protection()
        self.drafts._expire_authorizations()
        # Changing mode with armed records could turn a dry test into a write.
        if enabled and dry_run != self.dry_run and self.store.armed_autobook_authorizations():
            raise ValueError("Disarm all authorizations before changing execution mode.")
        self.enabled = enabled
        if enabled:
            self.dry_run = dry_run
        self.store.add_audit_event("library.autobook.executor", "runtime_configured",
                                   {"enabled": enabled, "dry_run": self.dry_run})
        return self.status()

    def _payload(self, row):
        return json.loads(self.drafts._require_protection().unprotect(bytes(row["encrypted_payload"])).decode())

    @staticmethod
    def _policy(draft):
        facts = {"verified_on": LibrarySpaceBookingPreviewCapability.POLICY_VERIFIED_ON,
                 "policy_sources": LibrarySpaceBookingPreviewCapability.POLICY_SOURCES,
                 "facility": LibraryShadowScheduler._facility_policy(draft.facility_type)}
        return hashlib.sha256(json.dumps(facts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _digest(self, row):
        return hmac.new(self.drafts._key, (row["id"] + hashlib.sha256(bytes(row["encrypted_payload"])).hexdigest()).encode(),
                        hashlib.sha256).hexdigest()

    def _row(self, identity):
        return self.store.get_autobook_authorization(identity)

    def arm(self, identity, digest):
        if not self.enabled:
            raise ValueError("Enable the local runtime explicitly before arming.")
        row = self._row(identity)
        payload = self._payload(row)
        draft = AutobookPilotDraft.model_validate(payload["exact_target"])
        if payload.get("capability_version") != 2 or not hmac.compare_digest(self._digest(row), digest):
            raise ValueError("Legacy or changed authorization; review a fresh authorization.")
        if not hmac.compare_digest(self._policy(draft), payload["policy_digest"]):
            raise ValueError("Policy changed; create a fresh authorization.")
        if draft.prepare_at <= utc_now() + timedelta(seconds=30):
            raise ValueError("Preparation must still be at least 30 seconds in the future.")
        self.store.arm_autobook(identity, utc_now().isoformat(), dry_run=self.dry_run)
        self.store.add_audit_event("library.autobook.authorization", "armed", {"authorization_id": identity, "dry_run": self.dry_run})
        return self.public(self._row(identity))

    def disarm(self, identity, action):
        result = self.drafts.change_authorization(identity, action)
        self.store.update_autobook_runtime(identity, utc_now().isoformat(), phase=action + "d" if action == "pause" else "revoked", armed=False)
        return self.public(self._row(identity))

    def public(self, row):
        result = self.drafts._public_authorization(row)
        runtime = self.store.autobook_runtime(row["id"])
        result.update(armed=bool(runtime["armed"]), phase=runtime["phase"], error_code=runtime["error_code"],
                      date_check_count=runtime["date_check_count"], arming_digest=self._digest(row),
                      execution_enabled=self.enabled, dry_run=bool(runtime.get("dry_run", self.dry_run)),
                      next_run_at=result["exact_target"]["prepare_at"] if runtime["armed"] and row["state"] == "pending_executor" else None)
        if row["success_count"]:
            result["booking_writes_performed"] = 1
        return result

    def list(self):
        self.drafts._expire_authorizations()
        rows = self.store.list_library_autobook_authorizations()
        return {**self.status(), "authorization_count": len(rows), "authorizations": [self.public(row) for row in rows]}

    async def start(self):
        if self._worker is not None:
            return
        self.store.recover_autobook_preparation(utc_now().isoformat())
        self._stopping = False
        self._worker = asyncio.create_task(self._loop(), name="library-autobook-executor")

    async def stop(self):
        self._stopping = True
        self.enabled = False
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None
        for task in self._inflight.values():
            task.cancel()
        await asyncio.gather(*list(self._inflight.values()), return_exceptions=True)
        self._inflight.clear()

    async def _loop(self):
        while not self._stopping:
            try:
                await self.run_due_once(background=True)
            except Exception:
                # Surface bounded failure in audit without private target/error text.
                self.store.add_audit_event("library.autobook.executor", "tick_failed", {})
            await asyncio.sleep(1)

    async def run_due_once(self, *, background=False):
        if not self.enabled or self._tick_lock.locked():
            return 0
        async with self._tick_lock:
            self.drafts._expire_authorizations()
            count = 0
            for row in self.store.armed_autobook_authorizations():
                runtime = self.store.autobook_runtime(row["id"])
                if row["state"] != "pending_executor" or not runtime["armed"] or runtime["phase"] != "armed":
                    continue
                draft = AutobookPilotDraft.model_validate(self._payload(row)["exact_target"])
                if utc_now() < draft.prepare_at:
                    continue
                if not self.store.begin_autobook(row["id"], utc_now().isoformat()):
                    continue
                count += 1
                if background:
                    task = asyncio.create_task(self._run(row, draft))
                    self._inflight[row["id"]] = task
                    task.add_done_callback(lambda _task, key=row["id"]: self._inflight.pop(key, None))
                else:
                    await self._run(row, draft)
            return count

    def _guard(self, identity, draft):
        row = self._row(identity)
        if self._stopping or not self.enabled or not library_booking_host_is_loopback():
            raise F4Refusal("EXECUTOR_DISABLED")
        if row["state"] != "pending_executor" or not self.store.autobook_runtime(identity)["armed"]:
            raise F4Refusal("AUTHORIZATION_STOPPED")
        if bool(self.store.autobook_runtime(identity).get("dry_run", True)) != self.dry_run:
            raise F4Refusal("EXECUTION_MODE_CHANGED")
        if utc_now() >= draft.stop_at:
            raise F4Refusal("EXECUTION_WINDOW_EXPIRED")
        payload = self._payload(row)
        if payload.get("capability_version") != 2 or not all(payload.get(key) is True for key in (
                "future_booking_acknowledged", "policy_acceptance_acknowledged", "discussion_room_rules_acknowledged")):
            raise F4Refusal("AUTHORIZATION_INVALID")
        if not hmac.compare_digest(self._policy(draft), payload["policy_digest"]):
            raise F4Refusal("POLICY_CHANGED")

    async def _wait(self, identity, draft, when):
        while utc_now() < when:
            self._guard(identity, draft)
            await asyncio.sleep(min(1, (when - utc_now()).total_seconds()))
        self._guard(identity, draft)

    async def _bounded(self, identity, draft, call):
        self._guard(identity, draft)
        try:
            result = await asyncio.wait_for(call(), (draft.stop_at - utc_now()).total_seconds())
        except asyncio.TimeoutError:
            raise F4Refusal("EXECUTION_WINDOW_EXPIRED") from None
        self._guard(identity, draft)
        return result

    async def _read(self, identity, draft, capability, arguments):
        task = await self._bounded(identity, draft, lambda: self.tasks.submit_and_wait(
            capability, arguments, session_id="library-f4-pilot", correlation_id=identity))
        if task.status != TaskStatus.COMPLETED or not task.result:
            raise F4Refusal((task.error or {}).get("code", "LIBRARY_READ_FAILED"))
        if task.result.get("booking_writes_performed") != 0 or task.result.get("read_only") is not True:
            raise F4Refusal("READ_INVARIANT_FAILED")
        return task.result

    async def _run(self, row, draft):
        identity, claimed = row["id"], False
        attempt_id = str(uuid.uuid4())
        phase, error = "failed_before_submit", None
        try:
            self._guard(identity, draft)
            # No catch-up booking when Core wakes after the bounded grace period.
            if utc_now() - draft.prepare_at > timedelta(seconds=120):
                raise F4Refusal("MISSED_AFTER_RESTART")
            if utc_now() < draft.execution_at:
                async with self._browser_lock:
                    await self._read(identity, draft, "library.spaces.list_dates", {"facility_type": "discussion_room"})
                await self._wait(identity, draft, draft.execution_at)
            offered = False
            for check in range(draft.max_date_checks):
                self.store.update_autobook_runtime(identity, utc_now().isoformat(), checks=check + 1)
                async with self._browser_lock:
                    dates = await self._read(identity, draft, "library.spaces.list_dates", {"facility_type": "discussion_room"})
                if dates.get("facility_type") != "discussion_room" or dates.get("location") != "Main Library":
                    raise F4Refusal("DATE_CONTEXT_MISMATCH")
                today = utc_now().astimezone(HK_TZ).date()
                offered = draft.target_date in {today, today + timedelta(days=1)} and draft.target_date.isoformat() in dates.get("offered_dates", [])
                if offered:
                    break
                if check + 1 < draft.max_date_checks:
                    await self._wait(identity, draft, min(utc_now() + timedelta(seconds=draft.poll_interval_seconds), draft.stop_at))
            if not offered:
                raise F4Refusal("TARGET_DATE_NOT_OFFERED")
            async with self._browser_lock:
                preview = await self._read(identity, draft, "library.spaces.booking_preview", {
                    "facility_type": "discussion_room", "date": draft.target_date.isoformat(), "floor": draft.floor,
                    "room": draft.room, "start_time": draft.start_time, "end_time": draft.end_time,
                    "eligibility_category": draft.eligibility_category})
                if preview.get("ready") is not True:
                    raise F4Refusal("EXACT_SLOT_UNAVAILABLE")
                target = preview["target"]
                for key, value in {"facility_type": "discussion_room", "location": "Main Library", "booking_facility_type": "Discussion Room",
                                   "date": draft.target_date.isoformat(), "floor": draft.floor, "room": draft.room,
                                   "start_time": draft.start_time, "end_time": draft.end_time}.items():
                    if target.get(key) != value:
                        raise F4Refusal("EXACT_TARGET_MISMATCH")
                record = await self._bounded(identity, draft, lambda: self.connector.read_library_booking_record(target))
                limits = record.get("account_limits", {})
                if not isinstance(limits.get("complete"), bool):
                    raise F4Refusal("EXTENSION_UPDATE_REQUIRED")
                if record.get("record_page_marker_found") is not True or limits.get("complete") is not True:
                    raise F4Refusal("ACCOUNT_LIMITS_UNVERIFIED")
                if limits.get("empty_target_day_verified") is not True or limits.get("target_day_active_count") != 0:
                    raise F4Refusal("EXISTING_BOOKINGS_REQUIRE_MANUAL_REVIEW")
                if self.dry_run:
                    phase = "dry_run_ready_no_submission"
                    return
                prepared = await self._bounded(identity, draft, lambda: self.connector.prepare_library_space_booking({
                    "facility_type": "discussion_room", "target": target, "discussion_room_rules_acknowledged": True}))
                if prepared.get("ready_to_submit") is not True or prepared.get("exact_target_verified") is not True or prepared.get("booking_writes_performed") != 0:
                    raise F4Refusal("BOOKING_FORM_MISMATCH")
                # Last guard after every await; claim is durable before external Submit.
                self._guard(identity, draft)
                if not self.store.claim_library_autobook_attempt(identity, attempt_id, utc_now().isoformat(), require_armed=True):
                    raise F4Refusal("AUTHORIZATION_ALREADY_USED")
                claimed, phase = True, "outcome_unknown"
                result = await asyncio.wait_for(self.connector.submit_library_space_booking({
                    "target": target, "execution_id": attempt_id, "prepared_tab_id": prepared.get("prepared_tab_id"),
                    "policy_acceptance_acknowledged": True, "discussion_room_rules_acknowledged": True,
                    "not_after": draft.stop_at.isoformat()}), max(0.1, (draft.stop_at - utc_now()).total_seconds()))
                # A modal success notice is not an authoritative booking record.
                if result.get("booking_writes_performed") == 1 and result.get("submit_clicks_dispatched") == 1:
                    record = await self.connector.read_library_booking_record(target)
                    if (record.get("verified_exactly_once") is True and record.get("record_page_marker_found") is True
                            and record.get("exact_target_match_count") == 1
                            and record.get("account_limits", {}).get("strict_exact_target_count") == 1):
                        if self.store.confirm_library_autobook_attempt(identity, attempt_id, utc_now().isoformat(), record_match_count=1):
                            phase = "booking_record_verified"
                if phase != "booking_record_verified":
                    error = "BOOKING_OUTCOME_UNKNOWN"
        except asyncio.CancelledError:
            error = "CORE_STOPPED"
            raise
        except Exception as exc:
            error = exc.code if isinstance(exc, F4Refusal) else "BOOKING_OUTCOME_UNKNOWN" if claimed else "READ_OR_PREPARATION_FAILED"
        finally:
            # Unknown means unknown writes, never zero, and never automatic retry.
            self.store.update_autobook_runtime(identity, utc_now().isoformat(), phase=phase, armed=False, error_code=error)
            self.store.add_audit_event("library.autobook.attempt", phase,
                                       {"authorization_id": identity, "attempt_id": attempt_id if claimed else None, "error_code": error})
