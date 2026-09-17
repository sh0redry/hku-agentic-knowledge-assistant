from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "project"
sys.path.insert(0, str(PROJECT))

from api.app import create_api_app
from application import ApplicationContainer
from services.briefing import DailyBriefingService
from services.moodle import MoodleAssignmentService
from services.portal import PortalNoticeService
from services.timetable import TimetableService


HK_TZ = ZoneInfo("Asia/Hong_Kong")


def timetable_fixture() -> dict:
    return json.loads(
        (ROOT / "tests" / "fixtures" / "sis_timetable_sem1.json").read_text(
            encoding="utf-8"
        )
    )


def assignment(due_at: datetime, title: str = "Private assignment") -> dict:
    return {
        "event_id": "10789042",
        "module_id": "4209090",
        "course_id": None,
        "course_name": None,
        "title": title,
        "activity_type": "assignment",
        "due_at": due_at.isoformat(),
        "due_at_source": "machine",
        "source": "timeline",
    }


class DailyBriefingServiceTests(unittest.TestCase):
    def test_combines_ready_caches_without_browser_interaction(self):
        timetable = TimetableService()
        moodle = MoodleAssignmentService()
        notices = PortalNoticeService()
        data = timetable_fixture()
        timetable.update(data["term_label"], data["meetings"], {"kind": "fixture"})
        as_of = datetime.fromisoformat("2026-09-17T17:00:00+08:00")
        moodle.update(
            [assignment(as_of.astimezone(timezone.utc) + timedelta(days=2))],
            {
                "kind": "fixture",
                "window": {
                    "as_of": as_of.isoformat(),
                    "days_ahead": 14,
                    "ends_at": (as_of + timedelta(days=14)).isoformat(),
                },
            },
        )
        notices.update(
            [{
                "title": "Registry service update",
                "published_date": "2026-09-17",
                "source_label": "Academic Services",
                "url": "https://studentportal.hku.hk/news/123",
                "url_query_redacted": False,
            }],
            {"kind": "fixture"},
        )

        result = DailyBriefingService(timetable, moodle, notices).build(
            term_label=data["term_label"],
            as_of=as_of,
            days_ahead=7,
            max_cache_age_minutes=10080,
        )

        self.assertTrue(result["complete"])
        self.assertFalse(result["browser_interactions_performed"])
        self.assertEqual(result["domain_writes_performed"], 0)
        self.assertEqual(result["next_class"]["course_code"], "COMP1110")
        self.assertEqual(result["counts"]["remaining_classes_today"], 1)
        self.assertEqual(result["counts"]["upcoming_assignments"], 1)
        self.assertEqual(result["counts"]["recent_portal_notices"], 1)
        self.assertEqual(
            result["upcoming_assignments"][0]["title"], "Private assignment"
        )

    def test_missing_caches_are_explicit_not_empty_successes(self):
        result = DailyBriefingService(
            TimetableService(), MoodleAssignmentService(), PortalNoticeService()
        ).build(
            term_label=None,
            as_of=datetime.fromisoformat("2026-09-17T17:00:00+08:00"),
            days_ahead=7,
            max_cache_age_minutes=120,
        )

        self.assertFalse(result["complete"])
        self.assertEqual(result["source_status"]["timetable"]["status"], "missing")
        self.assertEqual(
            result["source_status"]["moodle_assignments"]["status"], "missing"
        )
        self.assertEqual(
            result["source_status"]["portal_notices"]["status"], "missing"
        )
        self.assertEqual(result["remaining_classes_today"], [])
        self.assertEqual(result["upcoming_assignments"], [])

    def test_term_mismatch_and_short_moodle_coverage_are_omitted(self):
        timetable = TimetableService()
        moodle = MoodleAssignmentService()
        notices = PortalNoticeService()
        data = timetable_fixture()
        timetable.update(data["term_label"], data["meetings"], {"kind": "fixture"})
        now = datetime.now(timezone.utc)
        moodle.update(
            [assignment(now + timedelta(days=2))],
            {
                "kind": "fixture",
                "window": {
                    "as_of": now.isoformat(),
                    "days_ahead": 3,
                    "ends_at": (now + timedelta(days=3)).isoformat(),
                },
            },
        )
        notices.update([], {"kind": "fixture"})

        result = DailyBriefingService(timetable, moodle, notices).build(
            term_label="2026-27 Sem 2",
            as_of=now,
            days_ahead=7,
            max_cache_age_minutes=120,
        )

        self.assertFalse(result["complete"])
        self.assertEqual(
            result["source_status"]["timetable"]["status"], "term_mismatch"
        )
        self.assertEqual(
            result["source_status"]["moodle_assignments"]["status"],
            "insufficient_coverage",
        )
        self.assertIsNone(result["next_class"])
        self.assertEqual(result["upcoming_assignments"], [])


class DailyBriefingIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=ROOT / "tests" / ".tmp")
        self.container = ApplicationContainer(Path(self.temp_dir.name) / "test.db")
        self.token = "briefing-test-token-" + "x" * 32
        self.client = TestClient(
            create_api_app(self.container, integration_token=self.token)
        )
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def test_api_is_cache_only_and_persists_only_a_private_summary(self):
        now = datetime.now(timezone.utc)
        data = timetable_fixture()
        self.container.timetable.update(
            data["term_label"], data["meetings"], {"kind": "fixture"}
        )
        self.container.moodle_assignments.update(
            [assignment(now + timedelta(days=2), "Secret deadline title")],
            {
                "kind": "fixture",
                "window": {
                    "as_of": now.isoformat(),
                    "days_ahead": 14,
                    "ends_at": (now + timedelta(days=14)).isoformat(),
                },
            },
        )
        self.container.portal_notices.update(
            [{
                "title": "Private Portal headline",
                "published_date": now.date().isoformat(),
                "source_label": "Registry",
                "url": "https://studentportal.hku.hk/news/private",
                "url_query_redacted": False,
            }],
            {"kind": "fixture"},
        )

        response = self.client.post(
            "/api/v1/integration/briefing/today",
            headers=self.headers,
            json={
                "term_label": data["term_label"],
                "days_ahead": 7,
                "max_cache_age_minutes": 120,
            },
        ).json()

        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertTrue(result["complete"])
        self.assertTrue(result["derived_locally"])
        self.assertFalse(result["browser_interactions_performed"])
        self.assertEqual(result["domain_writes_performed"], 0)
        self.assertEqual(result["upcoming_assignments"][0]["title"], "Secret deadline title")
        self.assertEqual(result["recent_portal_notices"][0]["title"], "Private Portal headline")

        stored = self.container.store.get_task(response["task"]["id"])
        self.assertFalse(stored.result["private_briefing_details_persisted"])
        self.assertNotIn("Secret deadline title", str(stored.result))
        self.assertNotIn("COMP1110", str(stored.result))
        self.assertNotIn("Private Portal headline", str(stored.result))
        self.assertNotIn("upcoming_assignments", stored.result)
        self.assertNotIn("remaining_classes_today", stored.result)
        self.assertNotIn("recent_portal_notices", stored.result)

    def test_invalid_window_is_rejected_at_api_boundary(self):
        response = self.client.post(
            "/api/v1/integration/briefing/today",
            headers=self.headers,
            json={"days_ahead": 15},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "INVALID_REQUEST")


if __name__ == "__main__":
    unittest.main()
