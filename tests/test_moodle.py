from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "project"
sys.path.insert(0, str(PROJECT))

from api.app import create_api_app
from application import ApplicationContainer
from browser_bridge.service import BrowserBridgeError


class MoodleDashboardIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=ROOT / "tests" / ".tmp")
        self.container = ApplicationContainer(Path(self.temp_dir.name) / "test.db")
        self.token = "moodle-test-token-" + "x" * 32
        self.client = TestClient(
            create_api_app(self.container, integration_token=self.token)
        )
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def test_portal_navigation_returns_diagnostics_without_course_data(self):
        bind_hku_tab = AsyncMock(
            return_value={
                "origin": "https://studentportal.hku.hk",
                "page_kind": "portal_home",
                "logged_in": True,
            }
        )
        open_moodle = AsyncMock(
            return_value={
                "read_only": True,
                "navigation_only": True,
                "moodle_write_requests_sent": 0,
                "source_origin": "https://studentportal.hku.hk",
                "source_page_kind": "portal_home",
                "target_origin": "https://moodle.hku.hk",
                "target_page_kind": "dashboard",
                "steps": ["portal_to_moodle"],
                "snapshot": {
                    "origin": "https://moodle.hku.hk",
                    "logged_in": True,
                    "page_kind": "dashboard",
                    "diagnostics": {
                        "parser_version": "0.3.5",
                        "dashboard_marker_found": True,
                        "login_marker_found": False,
                        "user_menu_found": True,
                        "course_link_candidate_count": 6,
                        "timeline_marker_found": True,
                        "upcoming_marker_found": True,
                        "todo_marker_found": False,
                    },
                },
            }
        )
        connector = self.container.connectors["sis_browser"]
        connector.bind_hku_tab = bind_hku_tab
        connector.open_moodle = open_moodle

        response = self.client.post(
            "/api/v1/integration/moodle/dashboard/inspect",
            headers=self.headers,
            json={},
        ).json()

        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertEqual(result["systems_contacted"], ["portal", "moodle"])
        self.assertTrue(result["navigation_interactions_performed"])
        self.assertEqual(result["domain_writes_performed"], 0)
        self.assertEqual(result["moodle_writes_performed"], 0)
        self.assertFalse(result["course_data_read"])
        self.assertFalse(result["assignment_data_read"])
        self.assertEqual(result["dashboard"]["page_kind"], "dashboard")
        self.assertEqual(
            result["dashboard"]["diagnostics"]["course_link_candidate_count"], 6
        )
        self.assertNotIn("courses", result["dashboard"])
        self.assertNotIn("assignments", result["dashboard"])
        bind_hku_tab.assert_awaited_once_with()
        open_moodle.assert_awaited_once_with()

        stored = self.container.store.get_task(response["task"]["id"])
        self.assertNotIn("courses", stored.result.get("dashboard", {}))
        self.assertNotIn("assignments", stored.result.get("dashboard", {}))

    def test_login_requirement_preserves_stable_error(self):
        connector = self.container.connectors["sis_browser"]
        connector.bind_hku_tab = AsyncMock(
            return_value={
                "origin": "https://studentportal.hku.hk",
                "page_kind": "portal_home",
                "logged_in": True,
            }
        )
        connector.open_moodle = AsyncMock(
            side_effect=BrowserBridgeError(
                "MOODLE_LOGIN_REQUIRED",
                "Complete the HKU Portal User login and any MFA in the Moodle tab.",
            )
        )

        response = self.client.post(
            "/api/v1/integration/moodle/dashboard/inspect",
            headers=self.headers,
            json={},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "MOODLE_LOGIN_REQUIRED")
        self.assertIn("MFA", response["error"]["recovery"])

    def test_authenticated_home_to_dashboard_is_reported_as_navigation(self):
        connector = self.container.connectors["sis_browser"]
        connector.bind_hku_tab = AsyncMock(
            return_value={
                "origin": "https://moodle.hku.hk",
                "page_kind": "home",
                "logged_in": True,
            }
        )
        connector.open_moodle = AsyncMock(
            return_value={
                "read_only": True,
                "navigation_only": True,
                "moodle_write_requests_sent": 0,
                "source_origin": "https://moodle.hku.hk",
                "source_page_kind": "home",
                "target_origin": "https://moodle.hku.hk",
                "target_page_kind": "dashboard",
                "steps": ["moodle_fixed_route_to_dashboard"],
                "snapshot": {
                    "origin": "https://moodle.hku.hk",
                    "logged_in": True,
                    "page_kind": "dashboard",
                    "diagnostics": {
                        "parser_version": "0.3.5",
                        "dashboard_marker_found": True,
                        "login_marker_found": False,
                        "user_menu_found": True,
                        "course_link_candidate_count": 0,
                        "timeline_marker_found": False,
                        "upcoming_marker_found": False,
                        "todo_marker_found": False,
                    },
                },
            }
        )

        response = self.client.post(
            "/api/v1/integration/moodle/dashboard/inspect",
            headers=self.headers,
            json={},
        ).json()

        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["systems_contacted"], ["moodle"])
        self.assertTrue(response["result"]["navigation_interactions_performed"])
        self.assertEqual(response["result"]["moodle_writes_performed"], 0)
        self.assertEqual(
            response["result"]["navigation"]["steps"],
            ["moodle_fixed_route_to_dashboard"],
        )

    def test_visible_courses_are_returned_but_not_persisted(self):
        connector = self.container.connectors["sis_browser"]
        connector.bind_hku_tab = AsyncMock(
            return_value={
                "origin": "https://moodle.hku.hk",
                "page_kind": "dashboard",
                "logged_in": True,
            }
        )
        connector.open_moodle = AsyncMock(
            return_value={
                "read_only": True,
                "navigation_only": True,
                "moodle_write_requests_sent": 0,
                "source_origin": "https://moodle.hku.hk",
                "source_page_kind": "dashboard",
                "target_origin": "https://moodle.hku.hk",
                "target_page_kind": "dashboard",
                "steps": ["target_already_open"],
                "snapshot": {},
            }
        )
        connector.list_moodle_courses = AsyncMock(
            return_value={
                "origin": "https://moodle.hku.hk",
                "logged_in": True,
                "page_kind": "dashboard",
                "courses": [
                    {
                        "course_id": "123",
                        "course_code": "COMP3297",
                        "section": "2B",
                        "name": "COMP3297-2B Software Engineering",
                        "state": "current",
                    }
                ],
                "diagnostics": {
                    "parser_version": "0.3.5",
                    "dashboard_marker_found": True,
                    "login_marker_found": False,
                    "user_menu_found": True,
                    "course_link_candidate_count": 1,
                    "timeline_marker_found": True,
                    "upcoming_marker_found": True,
                    "todo_marker_found": False,
                    "course_candidate_count": 1,
                    "parsed_course_count": 1,
                    "unparsed_course_candidate_count": 0,
                    "missing_course_id_candidate_count": 0,
                    "missing_course_name_candidate_count": 0,
                    "duplicate_course_candidate_count": 0,
                    "course_placeholder_candidate_count": 0,
                },
            }
        )

        response = self.client.post(
            "/api/v1/integration/moodle/courses/list",
            headers=self.headers,
            json={},
        ).json()

        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertEqual(result["course_list"]["course_count"], 1)
        self.assertEqual(result["course_list"]["courses"][0]["course_id"], "123")
        self.assertFalse(result["assignment_data_read"])
        self.assertFalse(result["grade_data_read"])
        self.assertEqual(result["moodle_writes_performed"], 0)
        self.assertEqual(
            self.container.moodle_courses.snapshot()["courses"][0]["course_code"],
            "COMP3297",
        )

        stored = self.container.store.get_task(response["task"]["id"])
        self.assertEqual(stored.result["course_count"], 1)
        self.assertFalse(stored.result["private_course_details_persisted"])
        self.assertNotIn("course_list", stored.result)
        self.assertNotIn("Software Engineering", str(stored.result))

    def test_upcoming_assignments_are_bounded_and_not_persisted(self):
        connector = self.container.connectors["sis_browser"]
        connector.bind_hku_tab = AsyncMock(
            return_value={
                "origin": "https://studentportal.hku.hk",
                "page_kind": "portal_home",
                "logged_in": True,
            }
        )
        connector.open_moodle = AsyncMock(
            return_value={
                "read_only": True,
                "navigation_only": True,
                "moodle_write_requests_sent": 0,
                "source_origin": "https://studentportal.hku.hk",
                "source_page_kind": "portal_home",
                "target_origin": "https://moodle.hku.hk",
                "target_page_kind": "dashboard",
                "steps": ["portal_to_moodle"],
                "snapshot": {},
            }
        )
        now = datetime.now(timezone.utc)
        connector.list_moodle_upcoming_assignments = AsyncMock(
            return_value={
                "origin": "https://moodle.hku.hk",
                "logged_in": True,
                "page_kind": "dashboard",
                "assignment_count": 3,
                "assignments": [
                    {
                        "event_id": "9000",
                        "module_id": "7000",
                        "course_id": "123",
                        "course_name": "COMP3297 Software Engineering",
                        "title": "Expired private task",
                        "activity_type": "assignment",
                        "due_at": (now - timedelta(hours=1)).isoformat(),
                        "due_at_source": "machine",
                        "source": "timeline",
                    },
                    {
                        "event_id": "9001",
                        "module_id": "7001",
                        "course_id": "123",
                        "course_name": "COMP3297 Software Engineering",
                        "title": "Private milestone",
                        "activity_type": "assignment",
                        "due_at": (now + timedelta(days=2)).isoformat(),
                        "due_at_source": "machine",
                        "source": "timeline",
                    },
                    {
                        "event_id": "9002",
                        "module_id": "7002",
                        "course_id": "456",
                        "course_name": "COMP3230 Operating Systems",
                        "title": "Far future quiz",
                        "activity_type": "quiz",
                        "due_at": (now + timedelta(days=30)).isoformat(),
                        "due_at_source": "machine",
                        "source": "upcoming",
                    },
                ],
                "diagnostics": {
                    "parser_version": "0.3.5",
                    "dashboard_marker_found": True,
                    "login_marker_found": False,
                    "user_menu_found": True,
                    "course_link_candidate_count": 5,
                    "timeline_marker_found": True,
                    "upcoming_marker_found": True,
                    "todo_marker_found": False,
                    "assignment_candidate_count": 3,
                    "parsed_assignment_count": 3,
                    "unparsed_assignment_candidate_count": 0,
                    "missing_assignment_title_candidate_count": 0,
                    "missing_assignment_due_at_candidate_count": 0,
                    "duplicate_assignment_candidate_count": 0,
                    "assignment_placeholder_candidate_count": 0,
                    "visible_assignment_date_text_candidate_count": 3,
                    "parsed_assignment_display_date_count": 0,
                    "inferred_assignment_year_count": 0,
                    "assignment_date_text_with_year_count": 0,
                    "assignment_date_text_with_month_name_count": 0,
                    "assignment_date_text_with_12_hour_time_count": 0,
                    "assignment_date_text_with_24_hour_time_count": 0,
                    "assignment_date_text_with_relative_day_count": 0,
                    "assignment_date_text_with_numeric_date_count": 0,
                },
            }
        )

        response = self.client.post(
            "/api/v1/integration/moodle/assignments/upcoming",
            headers=self.headers,
            json={"days_ahead": 14},
        ).json()

        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertTrue(result["assignment_data_read"])
        self.assertFalse(result["submission_data_read"])
        self.assertEqual(result["activity_pages_opened"], 0)
        self.assertEqual(result["moodle_writes_performed"], 0)
        self.assertEqual(result["assignment_list"]["assignment_count"], 1)
        self.assertEqual(
            result["assignment_list"]["assignments"][0]["title"],
            "Private milestone",
        )
        self.assertEqual(result["excluded"]["overdue_count"], 1)
        self.assertEqual(result["excluded"]["beyond_window_count"], 1)

        stored = self.container.store.get_task(response["task"]["id"])
        self.assertEqual(stored.result["assignment_count"], 1)
        self.assertFalse(stored.result["private_assignment_details_persisted"])
        self.assertNotIn("assignment_list", stored.result)
        self.assertNotIn("Private milestone", str(stored.result))

    def test_upcoming_assignment_window_is_strictly_bounded(self):
        response = self.client.post(
            "/api/v1/integration/moodle/assignments/upcoming",
            headers=self.headers,
            json={"days_ahead": 91},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "INVALID_REQUEST")

    def test_incomplete_assignment_parse_fails_closed(self):
        connector = self.container.connectors["sis_browser"]
        connector.bind_hku_tab = AsyncMock(
            return_value={
                "origin": "https://moodle.hku.hk",
                "page_kind": "dashboard",
                "logged_in": True,
            }
        )
        connector.open_moodle = AsyncMock(
            return_value={
                "steps": ["target_already_open"],
                "snapshot": {},
            }
        )
        connector.list_moodle_upcoming_assignments = AsyncMock(
            return_value={
                "origin": "https://moodle.hku.hk",
                "logged_in": True,
                "page_kind": "dashboard",
                "assignment_count": 0,
                "assignments": [],
                "diagnostics": {
                    "parser_version": "0.3.5",
                    "dashboard_marker_found": True,
                    "login_marker_found": False,
                    "user_menu_found": True,
                    "course_link_candidate_count": 0,
                    "timeline_marker_found": True,
                    "upcoming_marker_found": True,
                    "todo_marker_found": False,
                    "assignment_candidate_count": 1,
                    "parsed_assignment_count": 0,
                    "unparsed_assignment_candidate_count": 1,
                    "missing_assignment_title_candidate_count": 0,
                    "missing_assignment_due_at_candidate_count": 1,
                    "duplicate_assignment_candidate_count": 0,
                    "assignment_placeholder_candidate_count": 0,
                    "visible_assignment_date_text_candidate_count": 1,
                    "parsed_assignment_display_date_count": 0,
                    "inferred_assignment_year_count": 0,
                    "assignment_date_text_with_year_count": 0,
                    "assignment_date_text_with_month_name_count": 1,
                    "assignment_date_text_with_12_hour_time_count": 1,
                    "assignment_date_text_with_24_hour_time_count": 0,
                    "assignment_date_text_with_relative_day_count": 0,
                    "assignment_date_text_with_numeric_date_count": 0,
                },
            }
        )

        response = self.client.post(
            "/api/v1/integration/moodle/assignments/upcoming",
            headers=self.headers,
            json={"days_ahead": 14},
        ).json()

        self.assertFalse(response["ok"])
        self.assertEqual(
            response["error"]["code"], "MOODLE_ASSIGNMENT_PARSE_INCOMPLETE"
        )
        self.assertIn("assignment parser diagnostics", response["error"]["recovery"])


if __name__ == "__main__":
    unittest.main()
