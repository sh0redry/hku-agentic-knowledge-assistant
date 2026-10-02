from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
from agents.models import TaskStatus
from services.library_autobook import AutobookPilotDraft, AutobookAuthorizationCreateRequest, LibraryAutobookDraftService
from services.library_autobook_executor import LibraryAutobookExecutor
from services.store import SQLiteStore


class Protector:
    def protect(self, data): return b"sealed:" + data[::-1]
    def unprotect(self, data): return data[7:][::-1]


class F4ExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.store = SQLiteStore(Path(self.directory.name) / "app.db")
        self.drafts = LibraryAutobookDraftService(self.store, Protector())
        self.now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        self.clock = patch("services.library_autobook.utc_now", side_effect=lambda: self.now)
        self.worker_clock = patch("services.library_autobook_executor.utc_now", side_effect=lambda: self.now)
        self.clock.start(); self.worker_clock.start()
        self.draft = AutobookPilotDraft.model_validate({
            "facility_type": "discussion_room", "target_date": "2026-09-30", "prepare_at": "2026-09-28 23:59:00",
            "execution_at": "2026-09-29 00:00:00", "stop_at": "2026-09-29 00:02:00", "floor": "Level 3",
            "room": "Discussion Room 2", "start_time": "10:00", "end_time": "11:00", "eligibility_category": "current_hku_students"})
        self.target = {"facility_type": "discussion_room", "location": "Main Library", "booking_facility_type": "Discussion Room",
                       "date": "2026-09-30", "floor": "Level 3", "room": "Discussion Room 2", "start_time": "10:00", "end_time": "11:00"}
        self.dates = ["2026-09-29", "2026-09-30"]
        self.preview_ready = True
        async def read(capability, arguments, **kwargs):
            result = {"read_only": True, "booking_writes_performed": 0}
            if capability == "library.spaces.list_dates":
                result.update(facility_type="discussion_room", location="Main Library", booking_facility_type="Discussion Room", offered_dates=self.dates)
            else:
                result.update(ready=self.preview_ready, target=self.target)
            return SimpleNamespace(status=TaskStatus.COMPLETED, result=result)
        self.tasks = SimpleNamespace(submit_and_wait=AsyncMock(side_effect=read))
        self.record = {"record_page_marker_found": True, "verified_exactly_once": False, "exact_target_match_count": 0,
                       "account_limits": {"complete": True, "target_day_active_count": 0, "empty_target_day_verified": True}}
        self.confirmed_record = {"record_page_marker_found": True, "verified_exactly_once": True, "exact_target_match_count": 1,
                                 "account_limits": {"strict_exact_target_count": 1}}
        self.connector = SimpleNamespace(read_library_booking_record=AsyncMock(side_effect=[self.record, self.confirmed_record]),
            prepare_library_space_booking=AsyncMock(return_value={"ready_to_submit": True, "exact_target_verified": True,
                                                                 "booking_writes_performed": 0, "prepared_tab_id": 7}),
            submit_library_space_booking=AsyncMock(return_value={"booking_writes_performed": 1, "submit_clicks_dispatched": 1}))
        self.worker = LibraryAutobookExecutor(self.drafts, self.tasks, self.connector)
        preview = self.drafts.authorization_preview(self.draft)
        self.created = self.drafts.create_authorization(AutobookAuthorizationCreateRequest(preview_digest=preview["preview_digest"],
            future_booking_acknowledged=True, policy_acceptance_acknowledged=True, discussion_room_rules_acknowledged=True))
        self.identity = self.created["id"]

    def tearDown(self):
        self.clock.stop(); self.worker_clock.stop(); self.directory.cleanup()

    def arm(self, dry_run=False):
        self.worker.configure(enabled=True, dry_run=dry_run)
        value = self.worker.public(self.worker._row(self.identity))
        self.worker.arm(self.identity, value["arming_digest"])

    def due(self): self.now = datetime(2026, 9, 28, 16, tzinfo=timezone.utc)

    def value(self): return self.worker.list()["authorizations"][0]

    async def test_disabled_and_unarmed_do_not_read_or_submit(self):
        self.due()
        self.assertEqual(await self.worker.run_due_once(), 0)
        self.worker.configure(enabled=True, dry_run=False)
        self.assertEqual(await self.worker.run_due_once(), 0)
        self.tasks.submit_and_wait.assert_not_called()
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_exact_live_once_and_authoritative_record(self):
        self.arm(); self.due()
        self.assertEqual(await self.worker.run_due_once(), 1)
        self.assertEqual(self.value()["state"], "completed")
        self.assertEqual(self.value()["phase"], "booking_record_verified")
        self.assertEqual(self.value()["success_count"], 1)
        self.assertEqual(await self.worker.run_due_once(), 0)
        self.connector.submit_library_space_booking.assert_awaited_once()
        self.assertEqual(self.connector.submit_library_space_booking.call_args.args[0]["not_after"], self.draft.stop_at.isoformat())
        self.assertNotIn(b"Discussion Room 2", Path(self.store.path).read_bytes())

    async def test_dry_run_does_not_select_or_submit_and_cannot_be_promoted(self):
        self.arm(dry_run=True)
        with self.assertRaises(ValueError): self.worker.configure(enabled=True, dry_run=False)
        self.worker.configure(enabled=False, dry_run=False)
        self.assertTrue(self.worker.dry_run)
        with self.assertRaises(ValueError): self.worker.configure(enabled=True, dry_run=False)
        self.worker.configure(enabled=True, dry_run=True)
        self.due(); await self.worker.run_due_once()
        self.assertEqual(self.value()["phase"], "dry_run_ready_no_submission")
        self.assertEqual(self.value()["attempt_count"], 0)
        self.connector.prepare_library_space_booking.assert_not_called()
        self.connector.submit_library_space_booking.assert_not_called()
        with self.assertRaises(ValueError): self.worker.arm(self.identity, self.value()["arming_digest"])

    async def test_ambiguous_submit_is_terminal_and_never_zero_writes(self):
        self.arm(); self.due()
        self.connector.submit_library_space_booking.side_effect = ConnectionError("private cookie")
        await self.worker.run_due_once()
        self.assertEqual(self.value()["state"], "outcome_unknown")
        self.assertEqual(self.value()["booking_writes_performed"], "unknown")
        self.assertEqual(await self.worker.run_due_once(), 0)
        self.connector.submit_library_space_booking.assert_awaited_once()
        self.assertNotIn("private cookie", str(self.value()))

    async def test_modal_success_without_record_is_not_success(self):
        self.confirmed_record["exact_target_match_count"] = 0
        self.confirmed_record["account_limits"]["strict_exact_target_count"] = 0
        self.arm(); self.due(); await self.worker.run_due_once()
        self.assertEqual(self.value()["state"], "outcome_unknown")

    async def test_multiple_exact_records_is_not_success(self):
        self.confirmed_record["exact_target_match_count"] = 2
        self.confirmed_record["account_limits"]["strict_exact_target_count"] = 2
        self.arm(); self.due(); await self.worker.run_due_once()
        self.assertEqual(self.value()["state"], "outcome_unknown")
        self.assertFalse(self.store.confirm_library_autobook_attempt(self.identity, "wrong", self.now.isoformat(), record_match_count=2))

    async def test_preparation_finishing_after_deadline_cannot_dispatch(self):
        self.arm(); self.due()
        original = self.connector.prepare_library_space_booking.return_value
        async def slow_prepare(*_args):
            self.now = self.draft.stop_at.astimezone(timezone.utc)
            return original
        self.connector.prepare_library_space_booking.side_effect = slow_prepare
        await self.worker.run_due_once()
        self.assertEqual(self.value()["error_code"], "EXECUTION_WINDOW_EXPIRED")
        self.assertEqual(self.value()["attempt_count"], 0)
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_parallel_ticks_have_one_durable_occurrence(self):
        import asyncio
        self.arm(); self.due()
        counts = await asyncio.gather(self.worker.run_due_once(), self.worker.run_due_once())
        self.assertEqual(sum(counts), 1)
        self.connector.submit_library_space_booking.assert_awaited_once()

    async def test_existing_or_unverified_records_stop_before_form(self):
        self.record["account_limits"]["complete"] = False
        self.arm(); self.due(); await self.worker.run_due_once()
        self.assertEqual(self.value()["error_code"], "ACCOUNT_LIMITS_UNVERIFIED")
        self.assertEqual(self.value()["booking_writes_performed"], 0)
        self.connector.prepare_library_space_booking.assert_not_called()

    async def test_existing_daily_booking_is_not_treated_as_remaining_quota(self):
        self.record["account_limits"].update(target_day_active_count=1, empty_target_day_verified=False)
        self.arm(); self.due(); await self.worker.run_due_once()
        self.assertEqual(self.value()["error_code"], "EXISTING_BOOKINGS_REQUIRE_MANUAL_REVIEW")
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_pause_during_form_preparation_prevents_claim_and_submit(self):
        self.arm(); self.due()
        original = self.connector.prepare_library_space_booking.return_value
        async def prepare(*_args):
            self.worker.disarm(self.identity, "pause")
            return original
        self.connector.prepare_library_space_booking.side_effect = prepare
        await self.worker.run_due_once()
        self.assertEqual(self.value()["state"], "paused")
        self.assertEqual(self.value()["attempt_count"], 0)
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_policy_change_and_expired_window_do_not_submit(self):
        self.arm(); self.due()
        with patch.object(self.worker, "_policy", return_value="changed"):
            await self.worker.run_due_once()
        self.assertEqual(self.value()["error_code"], "POLICY_CHANGED")
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_restart_after_claim_never_replays(self):
        self.arm(); self.due()
        self.assertTrue(self.store.begin_autobook(self.identity, self.now.isoformat()))
        self.assertTrue(self.store.claim_library_autobook_attempt(self.identity, "attempt", self.now.isoformat(), require_armed=True))
        restarted = LibraryAutobookExecutor(self.drafts, self.tasks, self.connector)
        await restarted.start()
        try:
            self.assertFalse(restarted.enabled)
            self.assertEqual(restarted.list()["authorizations"][0]["phase"], "outcome_unknown")
            restarted.configure(enabled=True, dry_run=False)
            self.assertEqual(await restarted.run_due_once(), 0)
            self.connector.submit_library_space_booking.assert_not_called()
        finally: await restarted.stop()

    async def test_exact_target_mismatch_stops_before_record_read(self):
        self.target["room"] = "Discussion Room 19"
        self.arm(); self.due(); await self.worker.run_due_once()
        self.assertEqual(self.value()["error_code"], "EXACT_TARGET_MISMATCH")
        self.connector.read_library_booking_record.assert_not_called()

    async def test_target_date_not_offered_never_falls_back(self):
        self.draft.max_date_checks = 1
        self.dates = ["2026-09-29"]
        self.arm(); self.due()
        # Avoid real waiting: the persisted authorization has its own bounds.
        async def wait(_id, _draft, _when): self.now = _when
        with patch.object(self.worker, "_wait", side_effect=wait): await self.worker.run_due_once()
        self.assertIn(self.value()["error_code"], {"TARGET_DATE_NOT_OFFERED", "EXECUTION_WINDOW_EXPIRED"})
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_arming_digest_and_legacy_versions_rejected(self):
        self.worker.configure(enabled=True, dry_run=True)
        with self.assertRaises(ValueError): self.worker.arm(self.identity, "a" * 64)
        payload = self.worker._payload(self.worker._row(self.identity)); payload["capability_version"] = 1
        with patch.object(self.worker, "_payload", return_value=payload):
            with self.assertRaises(ValueError): self.worker.arm(self.identity, self.value()["arming_digest"])

    async def test_expiration_clears_armed_state_and_does_not_block_future_pilot(self):
        self.arm(dry_run=True)
        self.now = self.draft.stop_at.astimezone(timezone.utc) + timedelta(seconds=1)
        self.worker.configure(enabled=True, dry_run=False)
        self.assertEqual(self.value()["state"], "expired")
        self.assertFalse(self.value()["armed"])
        self.assertEqual(await self.worker.run_due_once(), 0)
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_only_one_authorization_can_be_armed(self):
        self.arm(dry_run=True)
        preview = self.drafts.authorization_preview(self.draft)
        another = self.drafts.create_authorization(AutobookAuthorizationCreateRequest(preview_digest=preview["preview_digest"],
            future_booking_acknowledged=True, policy_acceptance_acknowledged=True, discussion_room_rules_acknowledged=True))
        with self.assertRaisesRegex(ValueError, "only one"):
            self.worker.arm(another["id"], self.worker.public(self.worker._row(another["id"]))["arming_digest"])

    async def test_expiry_preserves_success_and_timestamps_without_rearming(self):
        self.arm(dry_run=True); self.due()
        await self.worker.run_due_once()
        before = self.value()
        self.now = self.draft.stop_at.astimezone(timezone.utc) + timedelta(seconds=1)
        after = self.value()
        self.assertEqual(after["state"], "expired")
        self.assertEqual(after["phase"], "dry_run_ready_no_submission")
        self.assertEqual(after["execution_result"], before["execution_result"])
        self.assertEqual(after["execution_result"]["source"], "executor")
        self.assertIsNotNone(after["started_at"])
        self.assertEqual(after["completed_at"], before["completed_at"])
        self.assertFalse(after["armed"])
        self.assertEqual(await self.worker.run_due_once(), 0)
        with self.assertRaises(ValueError): self.worker.arm(self.identity, after["arming_digest"])

    async def test_expiry_preserves_failure_and_redacted_diagnostics(self):
        self.preview_ready = False
        self.arm(dry_run=True); self.due(); await self.worker.run_due_once()
        self.now = self.draft.stop_at.astimezone(timezone.utc) + timedelta(seconds=1)
        value = self.value()
        self.assertEqual(value["execution_result"]["phase"], "failed_before_submit")
        self.assertEqual(value["execution_result"]["error_code"], "EXACT_SLOT_UNAVAILABLE")
        self.assertTrue(any(d["stage"] == "checking_availability" for d in value["diagnostics"]))
        import json
        self.assertNotIn("Discussion Room", json.dumps(value["diagnostics"]))
        self.assertEqual(value["attempt_count"], 0)

    async def test_legacy_expired_result_recovers_from_audit_read_only(self):
        self.arm(dry_run=True); self.due(); await self.worker.run_due_once()
        with self.store._connection() as db:
            db.execute("UPDATE library_autobook_runtime SET phase='expired', execution_result_json=NULL WHERE authorization_id=?", (self.identity,))
        self.now = self.draft.stop_at.astimezone(timezone.utc) + timedelta(seconds=1)
        value = self.value()
        self.assertEqual(value["state"], "expired")
        self.assertEqual(value["execution_result"]["phase"], "dry_run_ready_no_submission")
        self.assertEqual(value["execution_result"]["source"], "legacy_audit")
        self.assertEqual(self.store.autobook_runtime(self.identity)["phase"], "expired")
        self.assertFalse(value["armed"])

    async def test_midnight_prepare_poll_release_with_simulated_clock(self):
        self.arm(dry_run=True)
        self.now = self.draft.prepare_at.astimezone(timezone.utc)
        reads = []
        original = self.tasks.submit_and_wait.side_effect
        date_checks = 0
        async def read(capability, arguments, **kwargs):
            nonlocal date_checks
            reads.append((capability, self.now))
            result = await original(capability, arguments, **kwargs)
            if capability == "library.spaces.list_dates":
                date_checks += 1
                result.result["offered_dates"] = ["2026-09-28", "2026-09-29"] if date_checks < 3 else self.dates
                result.result["navigation"] = {"session_recovery_attempted": date_checks == 1, "session_recovery_succeeded": date_checks == 1}
            return result
        async def advance(seconds): self.now += timedelta(seconds=seconds)
        self.tasks.submit_and_wait.side_effect = read
        with patch("services.library_autobook_executor.asyncio.sleep", side_effect=advance):
            await self.worker.run_due_once()
        value = self.value()
        self.assertEqual(value["execution_result"]["phase"], "dry_run_ready_no_submission")
        self.assertEqual(value["date_check_count"], 2)
        preview_times = [when for capability, when in reads if capability == "library.spaces.booking_preview"]
        self.assertEqual(preview_times, [self.draft.execution_at.astimezone(timezone.utc) + timedelta(seconds=15)])
        self.assertTrue(any(d.get("session_recovery_succeeded") for d in value["diagnostics"]))
        self.connector.prepare_library_space_booking.assert_not_called()
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_midnight_stop_bound_and_login_refusal_are_terminal(self):
        self.arm(dry_run=True); self.due()
        self.tasks.submit_and_wait.return_value = SimpleNamespace(status=TaskStatus.FAILED,
            result=None, error={"code": "LIBRARY_LOGIN_REQUIRED"})
        self.tasks.submit_and_wait.side_effect = None
        await self.worker.run_due_once()
        self.assertEqual(self.value()["execution_result"]["error_code"], "LIBRARY_LOGIN_REQUIRED")
        self.assertEqual(await self.worker.run_due_once(), 0)
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_midnight_poll_expires_without_fallback_or_submit(self):
        self.arm(dry_run=True)
        self.now = self.draft.execution_at.astimezone(timezone.utc)
        self.dates = ["2026-09-29"]
        async def advance(seconds): self.now += timedelta(seconds=seconds)
        # Eight checks stop after 105 seconds, before the 120-second deadline.
        with patch("services.library_autobook_executor.asyncio.sleep", side_effect=advance):
            await self.worker.run_due_once()
        self.assertEqual(self.value()["execution_result"]["error_code"], "TARGET_DATE_NOT_OFFERED")
        self.assertEqual(self.value()["date_check_count"], 8)
        self.assertTrue(all(call.args[0] == "library.spaces.list_dates" for call in self.tasks.submit_and_wait.call_args_list))
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_midnight_date_read_crossing_stop_deadline_cannot_continue(self):
        self.arm(dry_run=True); self.due()
        original = self.tasks.submit_and_wait.side_effect
        async def late(capability, arguments, **kwargs):
            result = await original(capability, arguments, **kwargs)
            self.now = self.draft.stop_at.astimezone(timezone.utc)
            return result
        self.tasks.submit_and_wait.side_effect = late
        await self.worker.run_due_once()
        self.assertEqual(self.value()["execution_result"]["error_code"], "EXECUTION_WINDOW_EXPIRED")
        self.assertEqual(self.tasks.submit_and_wait.await_count, 1)
        self.connector.read_library_booking_record.assert_not_called()
        self.connector.submit_library_space_booking.assert_not_called()

    async def test_new_pre_submit_stages_recover_after_restart_without_replay(self):
        self.arm(dry_run=True); self.due()
        self.store.begin_autobook(self.identity, self.now.isoformat())
        self.worker._stage(self.identity, "waiting_for_release")
        self.store.recover_autobook_preparation(self.now.isoformat())
        value = self.value()
        self.assertFalse(value["armed"])
        self.assertEqual(value["phase"], "interrupted")
        self.assertEqual(value["error_code"], "CORE_RESTARTED")
        self.assertEqual(await self.worker.run_due_once(), 0)
        self.connector.submit_library_space_booking.assert_not_called()

    def test_old_runtime_schema_migrates_without_inventing_execution_success(self):
        import sqlite3
        old_path = Path(self.directory.name) / "old.db"
        db = sqlite3.connect(old_path)
        try:
            db.executescript("""CREATE TABLE library_autobook_runtime (
                authorization_id TEXT PRIMARY KEY, armed INTEGER NOT NULL DEFAULT 0,
                dry_run INTEGER NOT NULL DEFAULT 1, phase TEXT NOT NULL DEFAULT 'not_armed',
                date_check_count INTEGER NOT NULL DEFAULT 0, error_code TEXT, updated_at TEXT NOT NULL);
                INSERT INTO library_autobook_runtime VALUES ('legacy',0,1,'expired',0,NULL,'2026-10-02T10:00:00Z');""")
        finally:
            db.close()
        migrated = SQLiteStore(old_path)
        self.assertIsNone(migrated.autobook_execution_details("legacy")["execution_result"])
        self.assertEqual(migrated.autobook_runtime("legacy")["phase"], "expired")
        self.assertFalse(migrated.autobook_runtime("legacy")["armed"])
        self.assertIsNone(SQLiteStore(old_path).autobook_execution_details("legacy")["execution_result"])


if __name__ == "__main__": unittest.main()
