from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1] / "project"
sys.path.insert(0, str(PROJECT))

from services.library_shadow import LibraryShadowScheduler, HK_TZ
from services.store import SQLiteStore


class LibraryShadowDateSelectionTests(unittest.TestCase):
    def test_daily_observation_does_not_assume_preceding_calendar_day(self):
        instant = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
        scheduled, observation_date = LibraryShadowScheduler._next_occurrence(
            instant, [6], "09:00",
        )
        self.assertEqual(observation_date, date(2026, 9, 25))
        self.assertEqual(scheduled.astimezone(HK_TZ).strftime("%Y-%m-%d %H:%M"), "2026-09-25 09:00")

    def test_main_library_holiday_skip_and_chi_wah_separate_dates(self):
        observe = date(2026, 9, 25)
        main = LibraryShadowScheduler._choose_target_date(
            ["2026-09-25", "2026-09-27"], observe, [5, 6], set(),
        )
        chi_wah = LibraryShadowScheduler._choose_target_date(
            ["2026-09-25", "2026-09-26"], observe, [5, 6], set(),
        )
        self.assertEqual(main, date(2026, 9, 27))
        self.assertEqual(chi_wah, date(2026, 9, 26))
        self.assertIsNone(LibraryShadowScheduler._choose_target_date(
            ["2026-09-25", "2026-09-27"], observe, [6], {"2026-09-27"},
        ))

    def test_migrated_rule_cannot_resume_but_can_be_revoked(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent / ".tmp") as folder:
            store = SQLiteStore(Path(folder) / "shadow.db")
            store.create_library_shadow_rule({
                "id": "old-rule", "state": "active", "encrypted_payload": b"sealed",
                "created_at": "2026-09-24T00:00:00+00:00",
                "updated_at": "2026-09-24T00:00:00+00:00",
                "next_run_at": "2026-09-25T00:00:00+00:00",
                "expires_at": "2027-01-01T00:00:00+00:00",
                "max_runs": 20, "version": 1,
            })
            store.set_library_shadow_rule_state("old-rule", "migration_required", "2026-09-25T00:00:00+00:00")
            with self.assertRaises(ValueError):
                store.set_library_shadow_rule_state("old-rule", "active", "2026-09-25T00:01:00+00:00")
            updated = store.set_library_shadow_rule_state("old-rule", "revoked", "2026-09-25T00:02:00+00:00")
            self.assertEqual(updated["state"], "revoked")


if __name__ == "__main__":
    unittest.main()
