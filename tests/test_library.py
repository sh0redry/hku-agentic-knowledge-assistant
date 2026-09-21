from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "project"
sys.path.insert(0, str(PROJECT))

from api.app import create_api_app
from application import ApplicationContainer
from browser_bridge.service import BrowserBridgeError


class LibraryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=ROOT / "tests" / ".tmp")
        self.container = ApplicationContainer(Path(self.temp_dir.name) / "test.db")
        self.token = "library-test-token-" + "x" * 32
        self.client = TestClient(create_api_app(self.container, integration_token=self.token))
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def research_navigation(self, *, incomplete: int = 0) -> dict:
        return {
            "read_only": True,
            "navigation_only": True,
            "library_write_requests_sent": 0,
            "navigation_interactions_performed": True,
            "target_origin": "https://julac-hku.primo.exlibrisgroup.com",
            "target_page_kind": "catalog_results",
            "steps": ["library_fixed_route_to_research_results"],
            "snapshot": {
                "origin": "https://julac-hku.primo.exlibrisgroup.com",
                "logged_in": None,
                "page_kind": "catalog_results",
                "result_count": 1,
                "results": [{
                    "record_id": "alma991234",
                    "title": "Artificial intelligence",
                    "resource_type": "book",
                    "metadata": ["Hulick, Kathryn", "2016"],
                    "availability_label": "Available at Main Library",
                    "detail_url": "https://julac-hku.primo.exlibrisgroup.com/discovery/fulldisplay?docid=alma991234&vid=852JULAC_HKU%3AHKU&lang=en",
                }],
                "diagnostics": {
                    "parser_version": "0.2.2",
                    "results_marker_found": True,
                    "empty_results_marker_found": False,
                    "result_candidate_count": 1 + incomplete,
                    "parsed_result_count": 1,
                    "incomplete_result_candidate_count": incomplete,
                    "unsafe_result_url_candidate_count": 0,
                },
            },
        }

    def research_item_navigation(self) -> dict:
        return {
            "read_only": True,
            "navigation_only": True,
            "library_write_requests_sent": 0,
            "navigation_interactions_performed": True,
            "licensed_full_text_opened": 0,
            "target_origin": "https://julac-hku.primo.exlibrisgroup.com",
            "target_page_kind": "catalog_item",
            "steps": ["library_fixed_route_to_research_item"],
            "snapshot": {
                "origin": "https://julac-hku.primo.exlibrisgroup.com",
                "logged_in": None,
                "page_kind": "catalog_item",
                "record_id": "alma991234",
                "title": "Artificial intelligence",
                "resource_type": "book",
                "metadata": [{"label": "Publication", "value": "Hong Kong, 2026"}],
                "access_options": [
                    {"kind": "online", "availability": "available", "label": "Online access"},
                    {"kind": "physical", "availability": "available", "label": "Available at Main Library"},
                ],
                "detail_url": "https://julac-hku.primo.exlibrisgroup.com/discovery/fulldisplay?docid=alma991234&vid=852JULAC_HKU%3AHKU&lang=en",
                "diagnostics": {
                    "parser_version": "0.2.2",
                    "detail_marker_found": True,
                    "record_id_found": True,
                    "title_found": True,
                    "metadata_field_count": 1,
                    "access_option_candidate_count": 2,
                    "parsed_access_option_count": 2,
                    "unsafe_access_link_candidate_count": 1,
                },
            },
        }

    def hours_navigation(self, *, available: bool = True) -> dict:
        locations = [{
            "name": "Main Library",
            "periods": [
                {"period_label": "Mon 21 Sep", "hours_label": "8:30 am - 11:00 pm", "status": "open"},
                {"period_label": "Tue 22 Sep", "hours_label": "Closed", "status": "closed"},
            ],
        }] if available else []
        return {
            "read_only": True,
            "navigation_only": True,
            "library_write_requests_sent": 0,
            "navigation_interactions_performed": True,
            "target_origin": "https://lib.hku.hk",
            "target_page_kind": "library_hours",
            "steps": ["library_fixed_route_to_hours"],
            "snapshot": {
                "origin": "https://lib.hku.hk",
                "logged_in": None,
                "page_kind": "library_hours",
                "hours_available": available,
                "location_count": len(locations),
                "locations": locations,
                "source_url": "https://lib.hku.hk/general/hours/",
                "diagnostics": {
                    "parser_version": "0.1.1",
                    "hours_marker_found": True,
                    "empty_state_found": not available,
                    "row_count": 2,
                    "location_candidate_count": len(locations),
                    "parsed_location_count": len(locations),
                    "duplicate_location_candidate_count": 0,
                    "placeholder_location_count": 1 if not available else 0,
                },
            },
        }

    def test_research_search_returns_rows_without_persisting_query_or_titles(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_research = AsyncMock(return_value=self.research_navigation())
        response = self.client.post(
            "/api/v1/integration/library/research/search",
            headers=self.headers,
            json={"query": "artificial intelligence", "field": "title", "limit": 10},
        ).json()
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["library_writes_performed"], 0)
        self.assertEqual(response["result"]["result_count"], 1)
        stored = self.container.store.get_task(response["task"]["id"])
        self.assertFalse(stored.input["query_persisted"])
        self.assertNotIn("artificial intelligence", str(stored.input).lower())
        self.assertFalse(stored.result["private_query_or_result_details_persisted"])
        self.assertNotIn("Artificial intelligence", str(stored.result))

    def test_research_parser_incomplete_fails_closed(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_research = AsyncMock(return_value=self.research_navigation(incomplete=1))
        response = self.client.post(
            "/api/v1/integration/library/research/search",
            headers=self.headers,
            json={"query": "databases"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "LIBRARY_RESEARCH_PARSE_INCOMPLETE")

    def test_space_authentication_is_manual_and_error_is_stable(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            side_effect=BrowserBridgeError("LIBRARY_LOGIN_REQUIRED", "Complete HKUL authentication in Chrome.")
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "single_study_room"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "LIBRARY_LOGIN_REQUIRED")
        self.assertIn("manual", response["error"]["recovery"].lower())

    def test_facility_catalog_is_local_read_only_and_policy_sourced(self):
        response = self.client.post(
            "/api/v1/integration/library/spaces/list-facilities",
            headers=self.headers,
            json={},
        ).json()
        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertTrue(result["derived_locally"])
        self.assertFalse(result["browser_interactions_performed"])
        self.assertEqual(result["booking_writes_performed"], 0)
        self.assertEqual(result["facility_count"], 3)
        self.assertEqual(
            {item["facility_type"] for item in result["facilities"]},
            {"single_study_room", "studio_editing_room", "study_table"},
        )
        self.assertTrue(all(item["availability_search_supported"] for item in result["facilities"]))
        single_room = next(
            item for item in result["facilities"]
            if item["facility_type"] == "single_study_room"
        )
        self.assertNotIn("sessions_per_day", single_room["booking_policy"])
        self.assertEqual(
            single_room["booking_policy"]["available_session_windows_per_weekday"], 3
        )
        self.assertEqual(len(result["policy_sources"]), 2)
        stored = self.container.store.get_task(response["task"]["id"])
        self.assertEqual(stored.result["facility_count"], 3)
        self.assertNotIn("facilities", stored.result)

    def test_hours_and_locations_reads_public_page_without_persisting_rows(self):
        connector = self.container.connectors["sis_browser"]
        connector.read_library_hours_and_locations = AsyncMock(
            return_value=self.hours_navigation()
        )
        response = self.client.post(
            "/api/v1/integration/library/hours-and-locations",
            headers=self.headers,
            json={},
        ).json()
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["library_writes_performed"], 0)
        self.assertTrue(response["result"]["hours_available"])
        self.assertEqual(response["result"]["locations"][0]["periods"][1]["status"], "closed")
        stored = self.container.store.get_task(response["task"]["id"])
        self.assertFalse(stored.result["location_hours_persisted"])
        self.assertNotIn("locations", stored.result)

    def test_hours_explicit_unavailable_state_is_not_reported_as_closed(self):
        connector = self.container.connectors["sis_browser"]
        connector.read_library_hours_and_locations = AsyncMock(
            return_value=self.hours_navigation(available=False)
        )
        response = self.client.post(
            "/api/v1/integration/library/hours-and-locations",
            headers=self.headers,
            json={},
        ).json()
        self.assertTrue(response["ok"])
        self.assertFalse(response["result"]["hours_available"])
        self.assertEqual(response["result"]["location_count"], 0)
        self.assertIn("does not mean", response["result"]["warnings"][0])

    def test_research_item_returns_bibliography_without_persisting_details(self):
        connector = self.container.connectors["sis_browser"]
        connector.read_library_research_item = AsyncMock(
            return_value=self.research_item_navigation()
        )
        response = self.client.post(
            "/api/v1/integration/library/research/item",
            headers=self.headers,
            json={"record_id": "alma991234"},
        ).json()
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["licensed_full_text_opened"], 0)
        self.assertEqual(response["result"]["metadata"][0]["label"], "Publication")
        stored = self.container.store.get_task(response["task"]["id"])
        self.assertFalse(stored.result["private_item_details_persisted"])
        self.assertNotIn("Hong Kong, 2026", str(stored.result))

    def test_research_access_options_suppress_external_links(self):
        connector = self.container.connectors["sis_browser"]
        connector.read_library_research_access_options = AsyncMock(
            return_value=self.research_item_navigation()
        )
        response = self.client.post(
            "/api/v1/integration/library/research/access-options",
            headers=self.headers,
            json={"record_id": "alma991234"},
        ).json()
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["access_option_count"], 2)
        self.assertEqual(response["result"]["external_access_links_returned"], 0)
        self.assertNotIn("url", response["result"]["access_options"][0])

    def test_research_record_id_rejects_urls_and_query_parameters(self):
        response = self.client.post(
            "/api/v1/integration/library/research/item",
            headers=self.headers,
            json={"record_id": "https://example.test/?token=secret"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "INVALID_REQUEST")

    def test_space_availability_has_zero_booking_writes(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(return_value={
            "read_only": True,
            "navigation_only": True,
            "library_write_requests_sent": 0,
            "booking_writes_performed": 0,
            "navigation_interactions_performed": True,
            "target_origin": "https://booking.lib.hku.hk",
            "target_page_kind": "space_availability",
            "facility_type": "single_study_room",
            "steps": ["library_fixed_route_to_space_availability"],
            "snapshot": {
                "origin": "https://booking.lib.hku.hk",
                "logged_in": True,
                "page_kind": "space_availability",
                "date": "2026-09-20",
                "available_slot_count": 1,
                "available_slots": [{"floor": "4/F", "room": "Study Room A", "start_time": "09:00", "end_time": "10:30", "status": "available"}],
                "diagnostics": {
                    "parser_version": "0.2.2",
                    "availability_marker_found": True,
                    "availability_legend_found": True,
                    "booked_legend_found": True,
                    "table_matrix_found": True,
                    "slot_candidate_count": 1,
                    "parsed_available_slot_count": 1,
                    "incomplete_available_slot_candidate_count": 0,
                },
            },
        })
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "single_study_room"},
        ).json()
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["booking_writes_performed"], 0)
        self.assertFalse(response["result"]["slot_selection_performed"])
        self.assertFalse(response["result"]["booking_form_opened"])


if __name__ == "__main__":
    unittest.main()
