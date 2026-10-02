from __future__ import annotations

import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1] / "project"
sys.path.insert(0, str(PROJECT))

from services.library_autobook import (
    AutobookAuthorizationCreateRequest, AutobookDraftCreateRequest,
    AutobookPilotDraft, LibraryAutobookDraftService,
    preview_autobook_pilot,
)
from services.store import SQLiteStore


class FakeProtector:
    def protect(self, data: bytes) -> bytes:
        return b"sealed:" + data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        if not data.startswith(b"sealed:"):
            raise ValueError("invalid protected payload")
        return data[7:][::-1]


class AutobookPilotDesignTests(unittest.TestCase):
    def draft(self, **changes):
        values = {
            "facility_type": "discussion_room",
            "target_date": "2026-09-30",
            "prepare_at": "2026-09-28 23:59:00",
            "execution_at": "2026-09-29 00:00:00",
            "stop_at": "2026-09-29 00:02:00",
            "floor": "Level 3",
            "room": "Discussion Room 2",
            "start_time": "10:00",
            "end_time": "11:00",
            "eligibility_category": "current_hku_students",
        }
        return AutobookPilotDraft.model_validate({**values, **changes})

    def test_preview_is_explicitly_non_authorizing(self):
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        with patch("services.library_autobook.utc_now", return_value=now):
            result = preview_autobook_pilot(self.draft())
        self.assertTrue(result["read_only"])
        self.assertFalse(result["standing_authorization_created"])
        self.assertFalse(result["unattended_submission_enabled"])
        self.assertEqual(result["booking_writes_performed"], 0)
        self.assertFalse(result["browser_interactions_performed"])
        self.assertEqual(result["pilot_scope"]["target_date"], "2026-09-30")
        self.assertEqual(result["pilot_scope"]["maximum_successful_bookings"], 1)
        self.assertGreaterEqual(len(result["unmet_gates"]), 3)

    def test_rejects_broad_or_inexact_scope(self):
        for change in [
            {"facility_type": "study_room"},
            {"room": "any room"},
            {"floor": "Level 4"},
            {"target_date": "2026-09-28"},
            {"stop_at": "2026-09-29 00:12:00"},
            {"start_time": "11:00", "end_time": "10:00"},
            {"eligibility_category": "hku_alumni"},
            {"extra_authority": True},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.draft(**change)

    def test_past_preparation_cannot_be_previewed(self):
        with patch("services.library_autobook.utc_now", return_value=datetime(2026, 9, 29, tzinfo=timezone.utc)):
            with self.assertRaisesRegex(ValueError, "will not roll"):
                preview_autobook_pilot(self.draft())

    def test_inert_draft_preview_create_revoke_and_restart(self):
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            store = SQLiteStore(Path(temporary) / "app.sqlite")
            service = LibraryAutobookDraftService(store, FakeProtector())
            with patch("services.library_autobook.utc_now", return_value=now):
                preview = service.preview(self.draft())
                request = AutobookDraftCreateRequest(
                    preview_digest=preview["preview_digest"], non_authorizing_acknowledged=True,
                )
                created = service.create(request)
            self.assertFalse(created["booking_authority"])
            self.assertIsNone(created["next_run_at"])
            self.assertEqual(created["booking_writes_performed"], 0)
            with self.assertRaisesRegex(ValueError, "consumed"):
                service.create(request)
            raw = (Path(temporary) / "app.sqlite").read_bytes()
            self.assertNotIn(b"Discussion Room 2", raw)
            restarted = LibraryAutobookDraftService(SQLiteStore(Path(temporary) / "app.sqlite"), FakeProtector())
            self.assertEqual(restarted.list()["draft_count"], 1)
            self.assertFalse(restarted.list()["unattended_submission_enabled"])
            revoked = restarted.revoke(created["id"])
            self.assertEqual(revoked["state"], "revoked")
            self.assertEqual(restarted.revoke(created["id"])["state"], "revoked")
            self.assertEqual(restarted.list()["drafts"][0]["state"], "revoked")

    def test_preview_expiry_and_missing_acknowledgement_fail_closed(self):
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            service = LibraryAutobookDraftService(SQLiteStore(Path(temporary) / "app.sqlite"), FakeProtector())
            with patch("services.library_autobook.utc_now", return_value=now):
                preview = service.preview(self.draft())
            with self.assertRaises(ValueError):
                AutobookDraftCreateRequest.model_validate({
                    "preview_digest": preview["preview_digest"],
                    "non_authorizing_acknowledged": False,
                })
            with patch("services.library_autobook.utc_now", return_value=now.replace(hour=13)):
                with self.assertRaisesRegex(ValueError, "expired"):
                    service.create(AutobookDraftCreateRequest(
                        preview_digest=preview["preview_digest"], non_authorizing_acknowledged=True,
                    ))
            self.assertEqual(service.list()["draft_count"], 0)

    def test_authorization_is_separate_one_time_and_not_executable(self):
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            database = Path(temporary) / "app.sqlite"
            store = SQLiteStore(database)
            service = LibraryAutobookDraftService(store, FakeProtector())
            with patch("services.library_autobook.utc_now", return_value=now):
                preview = service.authorization_preview(self.draft())
                request = AutobookAuthorizationCreateRequest(
                    preview_digest=preview["preview_digest"], future_booking_acknowledged=True,
                    policy_acceptance_acknowledged=True, discussion_room_rules_acknowledged=True,
                )
                authorized = service.create_authorization(request)
            self.assertEqual(authorized["state"], "pending_executor")
            self.assertFalse(authorized["execution_enabled"])
            self.assertIsNone(authorized["next_run_at"])
            self.assertEqual(authorized["attempt_count"], 0)
            self.assertEqual(authorized["success_count"], 0)
            with self.assertRaisesRegex(ValueError, "consumed"):
                service.create_authorization(request)
            self.assertNotIn(b"Discussion Room 2", database.read_bytes())
            restarted = LibraryAutobookDraftService(SQLiteStore(database), FakeProtector())
            # Keep restart/lifecycle checks at the same fixture time, rather
            # than expiring this authorization against the machine's date.
            with patch("services.library_autobook.utc_now", return_value=now):
                self.assertEqual(restarted.list_authorizations()["authorization_count"], 1)
                paused = restarted.change_authorization(authorized["id"], "pause")
                self.assertEqual(paused["state"], "paused")
                revoked = restarted.change_authorization(authorized["id"], "revoke")
                self.assertEqual(revoked["state"], "revoked")
                with self.assertRaises(ValueError):
                    restarted.change_authorization(authorized["id"], "pause")

    def test_authorization_requires_all_explicit_attestations(self):
        for missing in ("future_booking_acknowledged", "policy_acceptance_acknowledged",
                        "discussion_room_rules_acknowledged"):
            values = {
                "preview_digest": "a" * 64, "future_booking_acknowledged": True,
                "policy_acceptance_acknowledged": True,
                "discussion_room_rules_acknowledged": True,
            }
            values[missing] = False
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                AutobookAuthorizationCreateRequest.model_validate(values)

    def test_occurrence_claim_is_single_use_and_ambiguous_until_record_match(self):
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            store = SQLiteStore(Path(temporary) / "app.sqlite")
            service = LibraryAutobookDraftService(store, FakeProtector())
            with patch("services.library_autobook.utc_now", return_value=now):
                preview = service.authorization_preview(self.draft())
                authorization = service.create_authorization(AutobookAuthorizationCreateRequest(
                    preview_digest=preview["preview_digest"], future_booking_acknowledged=True,
                    policy_acceptance_acknowledged=True, discussion_room_rules_acknowledged=True,
                ))
            attempt_id = str(uuid.uuid4())
            self.assertFalse(store.claim_library_autobook_attempt(
                authorization["id"], str(uuid.uuid4()), now.isoformat(),
            ))
            instant = datetime(2026, 9, 28, 16, 1, tzinfo=timezone.utc).isoformat()
            self.assertTrue(store.claim_library_autobook_attempt(authorization["id"], attempt_id, instant))
            self.assertFalse(store.claim_library_autobook_attempt(authorization["id"], str(uuid.uuid4()), instant))
            self.assertEqual(service.list_authorizations()["authorizations"][0]["state"], "outcome_unknown")
            self.assertFalse(store.confirm_library_autobook_attempt(
                authorization["id"], attempt_id, instant, record_match_count=0,
            ))
            self.assertTrue(store.confirm_library_autobook_attempt(
                authorization["id"], attempt_id, instant, record_match_count=1,
            ))
            self.assertFalse(store.confirm_library_autobook_attempt(
                authorization["id"], attempt_id, instant, record_match_count=1,
            ))
            self.assertEqual(service.list_authorizations()["authorizations"][0]["success_count"], 1)

    def test_expired_authorization_cannot_be_claimed_or_reactivated(self):
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            store = SQLiteStore(Path(temporary) / "app.sqlite")
            service = LibraryAutobookDraftService(store, FakeProtector())
            with patch("services.library_autobook.utc_now", return_value=now):
                preview = service.authorization_preview(self.draft())
                authorization = service.create_authorization(AutobookAuthorizationCreateRequest(
                    preview_digest=preview["preview_digest"], future_booking_acknowledged=True,
                    policy_acceptance_acknowledged=True, discussion_room_rules_acknowledged=True,
                ))
            after_stop = datetime(2026, 9, 28, 16, 3, tzinfo=timezone.utc)
            with patch("services.library_autobook.utc_now", return_value=after_stop):
                self.assertEqual(service.list_authorizations()["authorizations"][0]["state"], "expired")
            self.assertFalse(store.claim_library_autobook_attempt(
                authorization["id"], str(uuid.uuid4()), after_stop.isoformat(),
            ))
            with self.assertRaises(ValueError):
                service.change_authorization(authorization["id"], "pause")

