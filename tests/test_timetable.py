from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "project"
sys.path.insert(0, str(PROJECT))

from api.app import create_api_app
from application import ApplicationContainer
from browser_bridge.service import BrowserBridgeError
from services.timetable import TimetableService


FIXTURES = ROOT / "tests" / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TimetableServiceTests(unittest.TestCase):
    def setUp(self):
        source = fixture("sis_timetable_sem1.json")
        self.service = TimetableService()
        self.service.update(
            source["term_label"], source["meetings"], {"kind": "sanitized_fixture"}
        )

    def test_next_class_uses_hong_kong_weekly_time(self):
        result = self.service.next_class(
            term_label="2026-27 Sem 1",
            as_of=datetime.fromisoformat("2026-09-14T12:00:00+08:00"),
            days_ahead=7,
        )
        self.assertEqual(result["next_class"]["course_code"], "COMP3230")
        self.assertEqual(result["next_class"]["minutes_until"], 60)
        self.assertFalse(result["browser_interactions_performed"])

    def test_free_slots_merge_classes_and_enforce_minimum(self):
        result = self.service.free_slots(
            term_label="2026-27 Sem 1",
            weekdays=["monday"],
            window_start="09:00",
            window_end="18:00",
            minimum_minutes=60,
        )
        self.assertEqual(
            result["free_slots"],
            [
                {"weekday": "monday", "start_time": "09:00", "end_time": "13:00", "duration_minutes": 240},
                {"weekday": "monday", "start_time": "15:50", "end_time": "18:00", "duration_minutes": 130},
            ],
        )

    def test_conflicts_report_each_exact_overlap(self):
        result = self.service.conflicts(
            term_label="2026-27 Sem 1",
            candidates=[
                {
                    "course_code": "COMP9999",
                    "section": "1A",
                    "weekday": "monday",
                    "start_time": "13:30",
                    "end_time": "15:10",
                    "room": None,
                }
            ],
        )
        self.assertTrue(result["has_conflicts"])
        self.assertEqual(result["conflict_count"], 2)
        self.assertTrue(all(item["overlap"]["duration_minutes"] > 0 for item in result["conflicts"]))

    def test_empty_term_is_a_valid_synchronized_timetable(self):
        empty = fixture("sis_timetable_sem2_empty.json")
        service = TimetableService()
        service.update(empty["term_label"], empty["meetings"], {"kind": "sanitized_fixture"})
        result = service.next_class(
            term_label=empty["term_label"],
            as_of=datetime.fromisoformat("2026-09-14T12:00:00+08:00"),
            days_ahead=7,
        )
        self.assertIsNone(result["next_class"])
        self.assertTrue(result["warnings"])


class TimetableIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=ROOT / "tests" / ".tmp")
        self.container = ApplicationContainer(Path(self.temp_dir.name) / "test.db")
        self.token = "timetable-test-token-" + "x" * 32
        self.client = TestClient(
            create_api_app(self.container, integration_token=self.token)
        )
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def test_sync_and_derived_api_share_one_read_only_cache(self):
        data = fixture("sis_timetable_sem1.json")
        self.container.connectors["sis_browser"].bind_hku_tab = AsyncMock(
            return_value={
                "origin": "https://studentportal.hku.hk",
                "page_kind": "portal_home",
                "logged_in": True,
            }
        )
        self.container.connectors["sis_browser"].open_weekly_timetable = AsyncMock(
            return_value={
                "read_only": True,
                "navigation_only": True,
                "timetable_write_requests_sent": 0,
                "source_origin": "https://studentportal.hku.hk",
                "source_page_kind": "portal_home",
                "target_origin": "https://sweb.hku.hk",
                "target_page_kind": "weekly_timetable",
                "steps": ["portal_to_weekly_timetable"],
                "snapshot": {
                    "origin": "https://sweb.hku.hk",
                    "page_kind": "weekly_timetable",
                    "term_label": data["term_label"],
                    "week_range": "14/09/2026 - 20/09/2026",
                    "meetings": data["meetings"],
                    "diagnostics": {
                        "parser_version": "0.2.1",
                        "term_detection_method": "page_label",
                        "timetable_marker_found": True,
                        "unparsed_candidate_count": 0,
                    },
                },
            }
        )
        sync = self.client.post(
            "/api/v1/integration/sis/timetable/sync-weekly",
            headers=self.headers,
            json={"term_label": data["term_label"]},
        ).json()
        self.assertTrue(sync["ok"])
        self.assertEqual(sync["result"]["timetable"]["meeting_count"], 7)
        self.assertEqual(
            sync["result"]["timetable"]["week_range"],
            "14/09/2026 - 20/09/2026",
        )
        self.assertEqual(
            sync["result"]["timetable"]["source"]["authoritative_for"],
            "weekly_schedule",
        )
        self.assertEqual(sync["result"]["domain_writes_performed"], 0)
        stored = self.container.store.get_task(sync["task"]["id"])
        self.assertFalse(stored.result["private_details_persisted"])
        self.assertNotIn("meetings", str(stored.result))

        next_class = self.client.post(
            "/api/v1/integration/sis/timetable/next-class",
            headers=self.headers,
            json={
                "term_label": data["term_label"],
                "as_of": "2026-09-14T12:00:00+08:00",
            },
        ).json()
        self.assertTrue(next_class["ok"])
        self.assertEqual(next_class["result"]["next_class"]["course_code"], "COMP3230")
        self.assertFalse(next_class["result"]["browser_interactions_performed"])

    def test_derived_api_requires_a_matching_sync(self):
        response = self.client.post(
            "/api/v1/integration/sis/timetable/free-slots",
            headers=self.headers,
            json={"term_label": "2026-27 Sem 2"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "TIMETABLE_NOT_SYNCED")

    def test_sync_reports_actionable_weekly_timetable_login_failure(self):
        self.container.connectors["sis_browser"].bind_hku_tab = AsyncMock(
            return_value={
                "origin": "https://studentportal.hku.hk",
                "page_kind": "portal_home",
                "logged_in": True,
            }
        )
        self.container.connectors["sis_browser"].open_weekly_timetable = AsyncMock(
            side_effect=BrowserBridgeError(
                "TIMETABLE_LOGIN_REQUIRED",
                "Complete HKU authentication for My Weekly Schedule in Chrome.",
            )
        )
        response = self.client.post(
            "/api/v1/integration/sis/timetable/sync-weekly",
            headers=self.headers,
            json={"term_label": "2026-27 Sem 2"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "TIMETABLE_LOGIN_REQUIRED")
        self.assertIn("My Weekly Schedule", response["error"]["recovery"])

    def test_exam_status_supports_not_published_without_writes(self):
        data = fixture("sis_exam_not_published.json")
        self.container.connectors["sis_browser"].inspect_page = AsyncMock(
            return_value={
                "origin": "https://sis-main.hku.hk",
                "page_kind": data["page_kind"],
                "term_label": data["term_label"],
                "exam_publication_state": data["exam_publication_state"],
                "exam_entries": data["exam_entries"],
                "diagnostics": {"parser_version": "0.3.0"},
            }
        )
        response = self.client.post(
            "/api/v1/integration/sis/timetable/exam-status",
            headers=self.headers,
            json={"term_label": data["term_label"]},
        ).json()
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["publication_state"], "not_published")
        self.assertEqual(response["result"]["domain_writes_performed"], 0)


if __name__ == "__main__":
    unittest.main()
