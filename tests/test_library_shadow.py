from __future__ import annotations

import sys
import tempfile
import unittest
import asyncio
from unittest.mock import patch
from types import SimpleNamespace
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1] / "project"
sys.path.insert(0, str(PROJECT))

from services.library_shadow import (
    LibraryShadowScheduler, HK_TZ, LibraryShadowRuleDefinition,
    ShadowPreviewRequest, ShadowCreateRequest,
)
from agents.models import TaskStatus
from services.store import SQLiteStore


class LibraryShadowDateSelectionTests(unittest.TestCase):
    def rule(self, **changes):
        value = dict(
            facility_type="study_room", execution_at="2026-09-29 00:00:00",
            target_date="2026-09-30", room_preference_order=[{"floor": "CPD-1", "room": "Study Room 2"}],
            session_preference_order=[{"start_time": "10:00", "end_time": "11:00"}],
            eligibility_category="current_hku_students", shadow_only=True,
        )
        return LibraryShadowRuleDefinition.model_validate({**value, **changes})

    def test_exact_midnight_is_hong_kong_and_past_time_never_rolls(self):
        rule = self.rule()
        before = datetime(2026, 9, 28, 15, 58, tzinfo=timezone.utc)
        scheduled, observed = LibraryShadowScheduler._exact_execution(before, rule)
        self.assertEqual(scheduled.isoformat(), "2026-09-28T16:00:00+00:00")
        self.assertEqual(observed, date(2026, 9, 29))
        with self.assertRaisesRegex(ValueError, "will not roll"):
            LibraryShadowScheduler._exact_execution(scheduled, rule)

    def test_invalid_intervals_and_past_target_rejected(self):
        for changes in [
            {"target_date": "2026-09-28"},
            {"session_preference_order": [{"start_time": "11:00", "end_time": "10:00"}]},
            {"execution_at": "2026-09-30 10:01:00"},
            {"target_weekdays": [0]},
        ]:
            with self.assertRaises(ValueError):
                self.rule(**changes)

    def test_main_library_holiday_skip_and_chi_wah_separate_dates(self):
        main = LibraryShadowScheduler._choose_target_date(
            ["2026-09-25", "2026-09-27"], date(2026, 9, 26),
        )
        chi_wah = LibraryShadowScheduler._choose_target_date(
            ["2026-09-25", "2026-09-26"], date(2026, 9, 26),
        )
        self.assertIsNone(main)
        self.assertEqual(chi_wah, date(2026, 9, 26))
        self.assertIsNone(LibraryShadowScheduler._choose_target_date(
            ["2026-09-25", "2026-09-27"], date(2026, 9, 28),
        ))

    def test_exact_end_time_and_expired_slots_filtered(self):
        rule = self.rule()
        slots = [{"floor": "CPD-1", "room": "Study Room 2", "status": "available",
                  "start_time": "10:00", "end_time": end} for end in ["10:30", "11:00"]]
        before = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)
        found = LibraryShadowScheduler._rank_candidates(rule, slots, "rule", "2026-09-30", before)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["end_time"], "11:00")
        self.assertEqual(LibraryShadowScheduler._rank_candidates(
            rule, slots, "rule", "2026-09-30", datetime(2026, 9, 30, 2, 0, tzinfo=timezone.utc)), [])

    def test_exact_target_search_or_unoffered_without_replay(self):
        async def scenario(offered):
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent / ".tmp") as folder:
                store = SQLiteStore(Path(folder) / "exact.db")
                calls = []
                async def submit(capability, arguments, **kwargs):
                    calls.append(capability)
                    if capability == "library.spaces.search_availability":
                        self.assertEqual(arguments["date"], "2026-09-30")
                        return SimpleNamespace(status=TaskStatus.COMPLETED, error=None, result={
                            "read_only": True, "booking_writes_performed": 0, "library_writes_performed": 0,
                            "domain_writes_performed": 0, "data_reads_performed": 1,
                            "slot_selection_performed": False, "booking_form_opened": False,
                            "result_set_complete": True, "date": "2026-09-30", "facility_type": "study_room",
                            "location": "Chi Wah Learning Commons", "booking_facility_type": "Study Room",
                            "available_slot_count": 1, "available_slots": [{"floor": "CPD-1", "room": "Study Room 2",
                                "start_time": "10:00", "end_time": "11:00", "status": "available"}],
                            "diagnostics": {"availability_marker_found": True, "availability_legend_found": True,
                                "booked_legend_found": True, "table_matrix_found": True, "selected_filters_found": True,
                                "result_set_complete": True, "unclassified_status_cell_count": 0},
                        })
                    return SimpleNamespace(status=TaskStatus.COMPLETED, error=None, result={
                        "read_only": True, "booking_writes_performed": 0,
                        "availability_search_submitted": False, "facility_type": "study_room",
                        "location": "Chi Wah Learning Commons", "booking_facility_type": "Study Room",
                        "offered_dates": ["2026-09-29", "2026-09-30"] if offered else ["2026-09-29"],
                    })
                protector = SimpleNamespace(protect=lambda x: x, unprotect=lambda x: x)
                with patch("services.library_shadow.WindowsUserDataProtector", return_value=protector):
                    scheduler = LibraryShadowScheduler(store, SimpleNamespace(submit_and_wait=submit))
                before = datetime(2026, 9, 28, 15, 58, tzinfo=timezone.utc)
                due = datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc)
                with patch("services.library_shadow.utc_now", return_value=before):
                    preview = scheduler.preview(ShadowPreviewRequest(rule=self.rule()))
                    self.assertEqual(preview["target_date"], "2026-09-30")
                    created = scheduler.create_rule(ShadowCreateRequest(
                        preview_digest=preview["rule_preview_digest"], shadow_only_acknowledged=True))
                with patch("services.library_shadow.utc_now", return_value=due):
                    self.assertEqual(await scheduler.run_due_once(due), 1)
                    self.assertEqual(await scheduler.run_due_once(due), 0)
                self.assertEqual(calls, ["library.spaces.list_dates"] + (["library.spaces.search_availability"] if offered else []))
                run = scheduler.list_runs(created["id"])["runs"][0]
                self.assertEqual(run["outcome"], "suggestion_ready" if offered else "target_date_not_offered")
                self.assertEqual(run["target_date"], "2026-09-30")
                self.assertEqual(run["booking_writes_performed"], 0)
        asyncio.run(scenario(False))
        asyncio.run(scenario(True))

    def test_migrated_rule_cannot_resume_but_can_be_revoked(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent / ".tmp") as folder:
            store = SQLiteStore(Path(folder) / "shadow.db")
            store.create_library_shadow_rule({
                "id": "old-rule", "state": "active", "encrypted_payload": b"sealed",
                "created_at": "2026-09-24T00:00:00+00:00",
                "updated_at": "2026-09-24T00:00:00+00:00",
                "next_run_at": "2026-09-25T00:00:00+00:00",
                "expires_at": "2027-01-01T00:00:00+00:00",
                "max_runs": 20, "version": 2,
            })
            protector = SimpleNamespace(protect=lambda x: x, unprotect=lambda x: x)
            async def migrate():
                with patch("services.library_shadow.WindowsUserDataProtector", return_value=protector):
                    scheduler = LibraryShadowScheduler(store, None)
                with patch("services.library_shadow.utc_now", return_value=datetime(2026, 9, 25, tzinfo=timezone.utc)):
                    await scheduler.start()
                    await scheduler.stop()
            asyncio.run(migrate())
            self.assertEqual(store.get_library_shadow_rule("old-rule")["state"], "migration_required")
            with self.assertRaises(ValueError):
                store.set_library_shadow_rule_state("old-rule", "active", "2026-09-25T00:01:00+00:00")
            updated = store.set_library_shadow_rule_state("old-rule", "revoked", "2026-09-25T00:02:00+00:00")
            self.assertEqual(updated["state"], "revoked")

    def test_release_window_validation(self):
        for changes in [
            {"prepare_at": "2026-09-28 23:49:00"},
            {"prepare_at": "2026-09-29 00:01:00"},
            {"stop_at": "2026-09-29 00:00:00"},
            {"stop_at": "2026-09-29 00:11:00"},
            {"poll_interval_seconds": 1}, {"max_date_checks": 21},
        ]:
            with self.assertRaises(ValueError):
                self.rule(**changes)

    def test_preparation_fresh_checks_bounds_pause_and_late_result(self):
        async def scenario(mode):
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent / ".tmp") as folder:
                store = SQLiteStore(Path(folder) / "release.db")
                clock = [datetime(2026, 9, 28, 15, 57, tzinfo=timezone.utc)]
                calls, phases = [], []
                rule = self.rule(prepare_at="2026-09-28 23:59:00", stop_at="2026-09-29 00:01:00",
                                 max_date_checks=3)
                async def submit(capability, arguments, **kwargs):
                    calls.append((capability, clock[0]))
                    if capability.endswith("search_availability"):
                        self.assertGreaterEqual(clock[0], rule.execution_at)
                        self.assertEqual(arguments["date"], "2026-09-30")
                        if mode == "late":
                            clock[0] = rule.stop_at
                        # Deliberately failed Search: the scheduler must not retry it.
                        return SimpleNamespace(status=TaskStatus.FAILED, error={"code": "TEST_SEARCH_ERROR"}, result=None)
                    if mode == "auth":
                        return SimpleNamespace(status=TaskStatus.FAILED, error={"code": "LIBRARY_LOGIN_REQUIRED"}, result=None)
                    # Preparation sees target; first post-release check does not. Never trust prep snapshot.
                    offered = len(calls) == 1 or (len(calls) >= 3 and mode not in {"exhaust", "deadline"})
                    return SimpleNamespace(status=TaskStatus.COMPLETED, error=None, result={
                        "read_only": True, "booking_writes_performed": 0, "availability_search_submitted": False,
                        "facility_type": "study_room", "location": "Chi Wah Learning Commons",
                        "booking_facility_type": "Study Room", "offered_dates": ["2026-09-30"] if offered else [],
                    })
                protector = SimpleNamespace(protect=lambda x: x, unprotect=lambda x: x)
                with patch("services.library_shadow.WindowsUserDataProtector", return_value=protector):
                    scheduler = LibraryShadowScheduler(store, SimpleNamespace(submit_and_wait=submit))
                with patch("services.library_shadow.utc_now", side_effect=lambda: clock[0]):
                    preview = scheduler.preview(ShadowPreviewRequest(rule=rule))
                    created = scheduler.create_rule(ShadowCreateRequest(
                        preview_digest=preview["rule_preview_digest"], shadow_only_acknowledged=True))
                    self.assertEqual(created["next_run_at"], "2026-09-28T15:59:00+00:00")
                    async def advance(when, row, definition):
                        phases.append(scheduler.list_runs(created["id"])["runs"][0]["phase"])
                        if mode == "pause":
                            scheduler.change_rule_state(created["id"], "pause")
                        clock[0] = rule.stop_at if mode == "deadline" else when
                        scheduler._ensure_window(row, definition)
                    scheduler._wait_until = advance
                    clock[0] = rule.prepare_at
                    await scheduler.run_due_once(clock[0])
                    await scheduler.run_due_once(clock[0])
                    result = scheduler.list_runs(created["id"])["runs"][0]
                expected = {"normal": "read_failed", "late": "observation_window_expired",
                            "pause": "rule_stopped_during_run", "exhaust": "target_date_not_offered",
                            "deadline": "observation_window_expired", "auth": "authentication_required"}
                self.assertEqual(result["outcome"], expected[mode])
                searches = [call for call in calls if call[0].endswith("search_availability")]
                self.assertEqual(len(searches), int(mode in {"normal", "late"}))
                self.assertEqual(result["booking_writes_performed"], 0)
                if mode in {"normal", "late"}:
                    self.assertEqual(phases, ["waiting_for_start", "waiting_for_date"])
                    self.assertEqual(result["date_check_count"], 2)
                if mode == "exhaust":
                    self.assertEqual(result["date_check_count"], 3)
                    self.assertEqual(len(calls), 4)  # one prep + three bounded checks
        for mode in ["normal", "exhaust", "pause", "deadline", "late", "auth"]:
            asyncio.run(scenario(mode))

    def test_waiting_rules_do_not_block_dispatch_or_replay(self):
        async def scenario():
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent / ".tmp") as folder:
                store = SQLiteStore(Path(folder) / "parallel.db")
                protector = SimpleNamespace(protect=lambda x: x, unprotect=lambda x: x)
                with patch("services.library_shadow.WindowsUserDataProtector", return_value=protector):
                    scheduler = LibraryShadowScheduler(store, None)
                now = datetime(2026, 9, 28, 15, 58, tzinfo=timezone.utc)
                with patch("services.library_shadow.utc_now", return_value=now):
                    for _ in range(2):
                        preview = scheduler.preview(ShadowPreviewRequest(rule=self.rule()))
                        scheduler.create_rule(ShadowCreateRequest(preview_digest=preview["rule_preview_digest"], shadow_only_acknowledged=True))
                gate, started = asyncio.Event(), []
                async def waiting(row, instant):
                    started.append(row["id"])
                    await gate.wait()
                scheduler._run_guarded = waiting
                due = now + timedelta(minutes=2)
                await scheduler.run_due_once(due, background=True)
                await asyncio.sleep(0)
                await scheduler.run_due_once(due, background=True)
                self.assertEqual(len(started), 2)
                gate.set()
                await asyncio.gather(*scheduler._inflight.values())
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
