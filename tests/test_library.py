from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "project"
sys.path.insert(0, str(PROJECT))

from api.app import create_api_app
from application import ApplicationContainer
from browser_bridge.service import BrowserBridgeError
from agents.models import TaskStatus
from agents.library.agent import hku_booking_today
from datetime import date, datetime, timezone
from services.library_booking import LibraryBookingPreviewRegistry


class LibraryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.booking_clock = patch("agents.library.agent.hku_booking_today", return_value=date(2026, 9, 20))
        self.booking_clock.start()
        self.addCleanup(self.booking_clock.stop)
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

    def space_navigation(
        self,
        *,
        date: str = "2026-09-20",
        slots: list | None = None,
        incomplete: int = 0,
        location: str = "Main Library",
        booking_facility_type: str = "Single Study Room (3 sessions)",
        facility_type: str = "single_study_room",
        page_count: int = 1,
        pages_read_count: int | None = None,
        booked_candidates: int = 0,
        unclassified_status_cells: int = 0,
        verified_empty: bool = False,
    ) -> dict:
        available_slots = slots if slots is not None else [{
            "floor": "4/F",
            "room": "Study Room A",
            "start_time": "09:00",
            "end_time": "10:30",
            "status": "available",
        }]
        pages_read = page_count if pages_read_count is None else pages_read_count
        return {
            "read_only": True,
            "navigation_only": True,
            "library_write_requests_sent": 0,
            "booking_writes_performed": 0,
            "navigation_interactions_performed": True,
            "target_origin": "https://booking.lib.hku.hk",
            "target_page_kind": "space_availability",
            "facility_type": facility_type,
            "location": location,
            "booking_facility_type": booking_facility_type,
            "date": date,
            "availability_search_submitted": True,
            "page_navigation_interactions_performed": pages_read > 1,
            "result_pages_read": pages_read,
            "steps": [
                "library_fixed_route_to_space_availability",
                "library_set_exact_availability_filters",
            ],
            "snapshot": {
                "origin": "https://booking.lib.hku.hk",
                "logged_in": True,
                "page_kind": "space_availability",
                "location": location,
                "booking_facility_type": booking_facility_type,
                "date": date,
                "source_last_updated_at": "2026-09-19 12:00:00",
                "page_number": 1,
                "page_count": page_count,
                "pages_read_count": pages_read,
                "result_set_complete": pages_read == page_count,
                "available_slot_count": len(available_slots),
                "available_slots": available_slots,
                "diagnostics": {
                    "parser_version": "0.3.5",
                    "availability_marker_found": True,
                    "availability_legend_found": True,
                    "booked_legend_found": True,
                    "table_matrix_found": True,
                    "matrix_signature": "12345678",
                    "selected_filters_found": True,
                    "result_set_complete": pages_read == page_count,
                    "verified_empty_result_found": verified_empty,
                    "facility_row_count": 1 if available_slots or booked_candidates or unclassified_status_cells else 0,
                    "status_cell_count": len(available_slots) + booked_candidates + unclassified_status_cells,
                    "unclassified_status_cell_count": unclassified_status_cells,
                    "neutral_nonselectable_cell_count": 0,
                    "slot_candidate_count": len(available_slots) + booked_candidates + incomplete,
                    "parsed_available_slot_count": len(available_slots),
                    "incomplete_available_slot_candidate_count": incomplete,
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
            json={"facility_type": "single_study_room", "date": "2026-09-20"},
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
        self.assertEqual(result["facility_count"], 5)
        self.assertEqual(result["availability_target_count"], 15)
        self.assertEqual(
            {item["facility_type"] for item in result["facilities"]},
            {"single_study_room", "studio_editing_room", "study_table", "study_room", "discussion_room"},
        )
        self.assertTrue(all(item["availability_search_supported"] for item in result["facilities"]))
        discussion_room = next(
            item for item in result["availability_targets"]
            if item["facility_type"] == "discussion_room"
        )
        self.assertTrue(discussion_room["availability_search_supported"])
        self.assertTrue(discussion_room["booking_preview_supported"])
        self.assertTrue(discussion_room["supervised_booking_supported"])
        single_room = next(
            item for item in result["facilities"]
            if item["facility_type"] == "single_study_room"
        )
        self.assertNotIn("sessions_per_day", single_room["booking_policy"])
        self.assertEqual(
            single_room["booking_policy"]["available_session_windows_per_weekday"], 3
        )
        self.assertEqual(len(result["policy_sources"]), 3)
        stored = self.container.store.get_task(response["task"]["id"])
        self.assertEqual(stored.result["facility_count"], 5)
        self.assertEqual(stored.result["availability_target_count"], 15)
        self.assertNotIn("facilities", stored.result)
        self.assertNotIn("availability_targets", stored.result)

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
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation()
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "single_study_room", "date": "2026-09-20"},
        ).json()
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["booking_writes_performed"], 0)
        self.assertFalse(response["result"]["slot_selection_performed"])
        self.assertFalse(response["result"]["booking_form_opened"])

    def test_space_availability_requires_exact_date(self):
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "study_room"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "INVALID_REQUEST")

    def test_hong_kong_booking_day_changes_at_local_midnight(self):
        self.assertEqual(
            hku_booking_today(datetime(2026, 9, 22, 15, 59, tzinfo=timezone.utc)),
            date(2026, 9, 22),
        )
        self.assertEqual(
            hku_booking_today(datetime(2026, 9, 22, 16, 0, tzinfo=timezone.utc)),
            date(2026, 9, 23),
        )

    def test_space_availability_rejects_out_of_window_before_browser(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock()
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "single_study_room", "date": "2026-09-22"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "LIBRARY_SPACE_DATE_OUT_OF_WINDOW")
        self.assertIn("2026-09-21", response["error"]["message"])
        connector.search_library_space_availability.assert_not_awaited()

    def test_space_availability_accepts_tomorrow_in_hong_kong(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(date="2026-09-21")
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "single_study_room", "date": "2026-09-21"},
        ).json()
        self.assertTrue(response["ok"])
        connector.search_library_space_availability.assert_awaited_once()

    def test_space_availability_rejects_unlisted_facility_before_browser(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock()
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "arbitrary_room", "date": "2026-09-20"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "INVALID_REQUEST")
        connector.search_library_space_availability.assert_not_awaited()

    def test_main_library_discussion_room_is_available_as_read_only_route(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(
                date="2026-09-20",
                facility_type="discussion_room",
                booking_facility_type="Discussion Room",
            )
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "discussion_room", "date": "2026-09-20"},
        ).json()
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["facility_type"], "discussion_room")
        self.assertEqual(response["result"]["booking_facility_type"], "Discussion Room")
        self.assertEqual(response["result"]["booking_writes_performed"], 0)
        connector.search_library_space_availability.assert_awaited_once_with(
            {"facility_type": "discussion_room", "date": "2026-09-20"}
        )

    def test_space_availability_fails_closed_when_results_are_paginated(self):
        connector = self.container.connectors["sis_browser"]
        navigation = self.space_navigation(page_count=2, pages_read_count=1)
        navigation["snapshot"]["diagnostics"]["unclassified_status_cell_count"] = 1
        connector.search_library_space_availability = AsyncMock(return_value=navigation)
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "single_study_room", "date": "2026-09-20"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "LIBRARY_SPACE_RESULTS_PAGINATED")

    def test_space_availability_accepts_complete_two_page_result(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(page_count=2)
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "single_study_room", "date": "2026-09-20"},
        ).json()
        self.assertTrue(response["ok"])
        self.assertTrue(response["result"]["result_set_complete"])
        self.assertEqual(response["result"]["result_pages_read"], 2)
        self.assertTrue(response["result"]["page_navigation_interactions_performed"])

    def test_space_availability_accepts_a_verified_empty_result(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(slots=[], verified_empty=True)
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "single_study_room", "date": "2026-09-20"},
        ).json()
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["available_slot_count"], 0)

    def test_space_availability_fails_closed_on_unverified_zero_candidates(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(slots=[])
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "single_study_room", "date": "2026-09-20"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "LIBRARY_SPACE_EMPTY_STATE_UNVERIFIED")

    def test_space_availability_fails_closed_on_unclassified_status_cell(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(slots=[], unclassified_status_cells=1)
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/search-availability",
            headers=self.headers,
            json={"facility_type": "single_study_room", "date": "2026-09-20"},
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "LIBRARY_SPACE_STATUS_PARSE_INCOMPLETE")

    def test_booking_preview_matches_exact_slot_without_booking_write(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation()
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json={
                "facility_type": "single_study_room",
                "date": "2026-09-20",
                "floor": "4/F",
                "room": "Study Room A",
                "start_time": "09:00",
                "end_time": "10:30",
                "eligibility_category": "current_hku_students",
            },
        ).json()
        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertTrue(result["ready"])
        self.assertEqual(result["reason"], "exact_slot_available")
        self.assertEqual(len(result["preview_digest"]), 64)
        self.assertFalse(result["preview"]["domain_write_authorized"])
        self.assertFalse(result["policy_acceptance_recorded"])
        self.assertEqual(result["booking_writes_performed"], 0)
        self.assertFalse(result["slot_selection_performed"])
        self.assertFalse(result["booking_form_opened"])
        connector.search_library_space_availability.assert_awaited_once_with(
            {"facility_type": "single_study_room", "date": "2026-09-20"}
        )
        stored = self.container.store.get_task(response["task"]["id"])
        self.assertFalse(stored.input["private_booking_target_persisted"])
        self.assertNotIn("Study Room A", str(stored.input))
        self.assertFalse(stored.result["private_preview_details_persisted"])
        self.assertNotIn("preview_digest", stored.result)

    def test_discussion_room_preview_uses_policy_and_rejects_duration_mismatch(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(side_effect=[
            self.space_navigation(
                facility_type="discussion_room",
                booking_facility_type="Discussion Room",
                page_count=2,
                slots=[{
                    "floor": "Level 3",
                    "room": "Discussion Room 1",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "status": "available",
                    "page_number": 2,
                }],
            ),
            self.space_navigation(
                facility_type="discussion_room",
                booking_facility_type="Discussion Room",
                page_count=2,
                slots=[{
                    "floor": "Level 3",
                    "room": "Discussion Room 1",
                    "start_time": "08:30",
                    "end_time": "10:00",
                    "status": "available",
                    "page_number": 1,
                }],
            ),
        ])
        request = {
            "facility_type": "discussion_room",
            "date": "2026-09-20",
            "floor": "Level 3",
            "room": "Discussion Room 1",
            "start_time": "10:00",
            "end_time": "11:00",
            "eligibility_category": "current_hku_space_students",
        }
        response = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json=request,
        ).json()
        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertTrue(result["ready"])
        self.assertEqual(result["target"]["facility_type"], "discussion_room")
        self.assertEqual(result["policy"]["booking_policy"]["maximum_minutes_per_day"], 120)
        self.assertEqual(result["policy"]["booking_policy"]["minimum_patron_count"], 2)
        self.assertIn("cannot be verified", " ".join(result["warnings"]))
        self.assertEqual(result["booking_writes_performed"], 0)
        self.assertFalse(result["slot_selection_performed"])
        self.assertFalse(result["booking_form_opened"])

        # F2 requires an additional discussion-room attestation, then permits a
        # local-only action draft bound to this exact server-issued preview.
        with self.assertRaises(Exception) as denied:
            self.container.actions.create_draft(
                "library.spaces.book",
                {
                    "preview_digest": result["preview_digest"],
                    "policy_acceptance_acknowledged": True,
                },
            )
        self.assertEqual(denied.exception.code, "LIBRARY_DISCUSSION_ROOM_RULES_ACK_REQUIRED")
        draft = self.container.actions.create_draft(
            "library.spaces.book",
            {
                "preview_digest": result["preview_digest"],
                "policy_acceptance_acknowledged": True,
                "discussion_room_rules_acknowledged": True,
            },
        )
        self.assertEqual(draft.preview["exact_target"]["facility_type"], "discussion_room")
        self.assertTrue(draft.preview["discussion_room_rules_acknowledged"])
        self.assertIn("at least two patrons", draft.preview["discussion_room_rules_attestation"])
        self.assertFalse(draft.preview["external_submission_enabled"])
        persisted_draft, _ = self.container.store.get_draft_with_token_hash(draft.id)
        self.assertNotIn("Discussion Room 1", str(persisted_draft.preview))
        self.assertTrue(persisted_draft.input["discussion_room_rules_acknowledged"])

        mismatch = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json={**request, "start_time": "08:30", "end_time": "10:00"},
        ).json()
        self.assertTrue(mismatch["ok"])
        self.assertFalse(mismatch["result"]["ready"])
        self.assertEqual(mismatch["result"]["reason"], "published_session_duration_mismatch")
        self.assertEqual(mismatch["result"]["observed_slot_duration_minutes"], 90)
        self.assertIsNone(mismatch["result"]["preview_digest"])
        connector.search_library_space_availability.assert_awaited()

    def test_booking_preview_rejects_out_of_window_before_browser(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock()
        response = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json={
                "facility_type": "single_study_room",
                "date": "2026-09-22",
                "room": "Study Room A",
                "start_time": "09:00",
                "end_time": "10:30",
                "eligibility_category": "current_hku_students",
            },
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "LIBRARY_SPACE_DATE_OUT_OF_WINDOW")
        connector.search_library_space_availability.assert_not_awaited()

    def test_f2_booking_draft_binds_process_issued_preview_and_stays_disabled(self):
        async def scenario():
            connector = self.container.connectors["sis_browser"]
            connector.search_library_space_availability = AsyncMock(
                return_value=self.space_navigation()
            )
            preview_task = await self.container.tasks.submit_and_wait(
                "library.spaces.booking_preview",
                {
                    "facility_type": "single_study_room",
                    "date": "2026-09-20",
                    "floor": "4/F",
                    "room": "Study Room A",
                    "start_time": "09:00",
                    "end_time": "10:30",
                    "eligibility_category": "current_hku_students",
                },
            )
            digest = preview_task.result["preview_digest"]
            draft = self.container.actions.create_draft(
                "library.spaces.book", {
                    "preview_digest": digest,
                    "policy_acceptance_acknowledged": True,
                }
            )
            self.assertEqual(draft.status, TaskStatus.AWAITING_CONFIRMATION)
            self.assertEqual(draft.preview["exact_target"]["room"], "Study Room A")
            self.assertFalse(draft.preview["external_submission_enabled"])
            persisted_draft, _ = self.container.store.get_draft_with_token_hash(draft.id)
            self.assertFalse(persisted_draft.preview["exact_target_persisted"])
            self.assertNotIn("Study Room A", str(persisted_draft.preview))

            confirmed, token = self.container.actions.confirm(
                draft.id, draft.preview_digest
            )
            self.assertEqual(confirmed.status, TaskStatus.QUEUED)
            with patch("config.LIBRARY_BOOKING_WRITES_ENABLED", False):
                task = self.container.actions.execute(
                    draft.id,
                    confirmation_token=token,
                    session_id="test-user",
                )
                await self.container.tasks._running[task.id]
            failed = self.container.store.get_task(task.id)
            self.assertEqual(failed.status, TaskStatus.FAILED)
            self.assertEqual(failed.error["code"], "LIBRARY_BOOKING_WRITE_DISABLED")
            self.assertEqual(failed.error["details"]["booking_writes_performed"], 0)
            self.assertFalse(failed.error["details"]["preview_consumed"])

            timeout_preview = await self.container.tasks.submit_and_wait(
                "library.spaces.booking_preview",
                {
                    "facility_type": "single_study_room",
                    "date": "2026-09-20",
                    "floor": "4/F",
                    "room": "Study Room A",
                    "start_time": "09:00",
                    "end_time": "10:30",
                    "eligibility_category": "current_hku_students",
                },
            )
            timeout_draft = self.container.actions.create_draft(
                "library.spaces.book", {
                    "preview_digest": timeout_preview.result["preview_digest"],
                    "policy_acceptance_acknowledged": True,
                }
            )
            timeout_confirmed, timeout_token = self.container.actions.confirm(
                timeout_draft.id, timeout_draft.preview_digest
            )
            connector.prepare_library_space_booking = AsyncMock(
                side_effect=BrowserBridgeError(
                    "BROWSER_TIMEOUT", "simulated F2 preparation timeout"
                )
            )
            connector.submit_library_space_booking = AsyncMock()
            with patch("config.LIBRARY_BOOKING_WRITES_ENABLED", True):
                timeout_task = self.container.actions.execute(
                    timeout_confirmed.id,
                    confirmation_token=timeout_token,
                    session_id="test-user",
                )
                await self.container.tasks._running[timeout_task.id]
            preparation_failed = self.container.store.get_task(timeout_task.id)
            self.assertEqual(preparation_failed.status, TaskStatus.FAILED)
            self.assertEqual(
                preparation_failed.error["code"],
                "LIBRARY_BOOKING_PREPARE_TIMEOUT",
            )
            self.assertEqual(
                preparation_failed.error["details"]["booking_writes_performed"], 0
            )
            self.assertEqual(
                preparation_failed.error["details"]["submit_clicks_dispatched"], 0
            )
            self.assertFalse(
                preparation_failed.error["details"]["preview_consumed"]
            )
            connector.submit_library_space_booking.assert_not_awaited()

            second = self.container.actions.create_draft(
                "library.spaces.book", {
                    "preview_digest": digest,
                    "policy_acceptance_acknowledged": True,
                }
            )
            confirmed_second, second_token = self.container.actions.confirm(
                second.id, second.preview_digest
            )
            connector.prepare_library_space_booking = AsyncMock(return_value={
                "ready_to_submit": True,
                "exact_target_verified": True,
                "booking_writes_performed": 0,
                "slot_selection_performed": True,
                "booking_form_opened": True,
                "prepared_tab_id": 42,
            })
            connector.submit_library_space_booking = AsyncMock(return_value={
                "read_only": False,
                "systems_contacted": ["hkul_booking"],
                "navigation_interactions_performed": True,
                "data_reads_performed": 2,
                "domain_writes_performed": 1,
                "library_writes_performed": 1,
                "booking_writes_performed": 1,
                "slot_selection_performed": True,
                "booking_form_opened": True,
                "submit_clicks_dispatched": 1,
                "outcome": "confirmed",
                "exact_target_verified_in_booking_record": True,
                "record_match_count": 1,
                "policy_acceptance_acknowledged": True,
                "diagnostics": {"parser_version": "0.1.0"},
            })
            with patch("config.LIBRARY_BOOKING_WRITES_ENABLED", True):
                second_task = self.container.actions.execute(
                    confirmed_second.id,
                    confirmation_token=second_token,
                    session_id="test-user",
                )
                await self.container.tasks._running[second_task.id]
            completed = self.container.store.get_task(second_task.id)
            self.assertEqual(completed.status, TaskStatus.COMPLETED)
            self.assertEqual(
                completed.result["booking_writes_performed"], 1
            )
            self.assertTrue(completed.result["exact_target_verified_in_booking_record"])
            self.assertEqual(completed.result["record_match_count"], 1)
            connector.prepare_library_space_booking.assert_awaited_once()
            connector.submit_library_space_booking.assert_awaited_once()
            with self.assertRaises(Exception) as consumed:
                self.container.actions.create_draft(
                    "library.spaces.book", {
                        "preview_digest": digest,
                        "policy_acceptance_acknowledged": True,
                    }
                )
            self.assertEqual(consumed.exception.code, "LIBRARY_BOOKING_PREVIEW_ALREADY_USED")

            # A response/validation failure after the submit connector was
            # entered is ambiguous; surface UNKNOWN and never retry it.
            unknown_preview = await self.container.tasks.submit_and_wait(
                "library.spaces.booking_preview",
                {
                    "facility_type": "single_study_room",
                    "date": "2026-09-20",
                    "floor": "4/F",
                    "room": "Study Room A",
                    "start_time": "09:00",
                    "end_time": "10:30",
                    "eligibility_category": "current_hku_students",
                },
            )
            unknown_digest = unknown_preview.result["preview_digest"]
            unknown_draft = self.container.actions.create_draft(
                "library.spaces.book", {
                    "preview_digest": unknown_digest,
                    "policy_acceptance_acknowledged": True,
                }
            )
            unknown_confirmed, unknown_token = self.container.actions.confirm(
                unknown_draft.id, unknown_draft.preview_digest
            )
            connector.submit_library_space_booking.reset_mock(
                side_effect=True, return_value=True
            )
            connector.submit_library_space_booking.side_effect = BrowserBridgeError(
                "BROWSER_NOT_CONNECTED", "simulated transport loss after dispatch"
            )
            with patch("config.LIBRARY_BOOKING_WRITES_ENABLED", True):
                unknown_task = self.container.actions.execute(
                    unknown_confirmed.id,
                    confirmation_token=unknown_token,
                    session_id="test-user",
                )
                await self.container.tasks._running[unknown_task.id]
            unknown_result = self.container.store.get_task(unknown_task.id)
            self.assertEqual(unknown_result.status, TaskStatus.UNKNOWN)
            self.assertEqual(
                unknown_result.error["code"], "LIBRARY_BOOKING_OUTCOME_UNKNOWN"
            )
            self.assertEqual(
                unknown_result.error["details"]["booking_writes_performed"],
                "unknown",
            )
            connector.submit_library_space_booking.assert_awaited_once()

        asyncio.run(scenario())

    def test_discussion_room_f2_one_shot_path_requires_attestation_and_binds_exact_slot(self):
        async def scenario():
            connector = self.container.connectors["sis_browser"]
            connector.search_library_space_availability = AsyncMock(return_value=self.space_navigation(
                date="2026-09-20",
                location="Main Library",
                booking_facility_type="Discussion Room",
                facility_type="discussion_room",
                slots=[{
                    "floor": "Level 3",
                    "room": "Discussion Room 2",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "status": "available",
                    "page_number": 1,
                }],
            ))
            preview_task = await self.container.tasks.submit_and_wait(
                "library.spaces.booking_preview",
                {
                    "facility_type": "discussion_room",
                    "date": "2026-09-20",
                    "floor": "Level 3",
                    "room": "Discussion Room 2",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "eligibility_category": "current_hku_students",
                },
            )
            digest = preview_task.result["preview_digest"]
            with self.assertRaises(Exception) as missing_attestation:
                self.container.actions.create_draft(
                    "library.spaces.book",
                    {"preview_digest": digest, "policy_acceptance_acknowledged": True},
                )
            self.assertEqual(
                missing_attestation.exception.code,
                "LIBRARY_DISCUSSION_ROOM_RULES_ACK_REQUIRED",
            )
            draft = self.container.actions.create_draft(
                "library.spaces.book",
                {
                    "preview_digest": digest,
                    "policy_acceptance_acknowledged": True,
                    "discussion_room_rules_acknowledged": True,
                },
            )
            confirmed, token = self.container.actions.confirm(draft.id, draft.preview_digest)
            connector.prepare_library_space_booking = AsyncMock(return_value={
                "ready_to_submit": True,
                "exact_target_verified": True,
                "booking_writes_performed": 0,
                "slot_selection_performed": True,
                "booking_form_opened": True,
                "prepared_tab_id": 42,
            })
            connector.submit_library_space_booking = AsyncMock(return_value={
                "read_only": False,
                "systems_contacted": ["hkul_booking"],
                "navigation_interactions_performed": True,
                "data_reads_performed": 2,
                "domain_writes_performed": 1,
                "library_writes_performed": 1,
                "booking_writes_performed": 1,
                "slot_selection_performed": True,
                "booking_form_opened": True,
                "submit_clicks_dispatched": 1,
                "outcome": "confirmed",
                "exact_target_verified_in_booking_record": True,
                "record_match_count": 1,
                "policy_acceptance_acknowledged": True,
                "diagnostics": {"parser_version": "0.1.0"},
            })
            with patch("config.LIBRARY_BOOKING_WRITES_ENABLED", True):
                task = self.container.actions.execute(
                    confirmed.id,
                    confirmation_token=token,
                    session_id="test-user",
                )
                await self.container.tasks._running[task.id]
            completed = self.container.store.get_task(task.id)
            self.assertEqual(completed.status, TaskStatus.COMPLETED)
            self.assertEqual(completed.result["booking_writes_performed"], 1)
            self.assertTrue(completed.result["discussion_room_rules_acknowledged"])
            self.assertEqual(
                connector.prepare_library_space_booking.await_args.args[0]["target"]["facility_type"],
                "discussion_room",
            )
            self.assertTrue(
                connector.prepare_library_space_booking.await_args.args[0]["discussion_room_rules_acknowledged"]
            )
            self.assertTrue(
                connector.submit_library_space_booking.await_args.args[0]["discussion_room_rules_acknowledged"]
            )

        asyncio.run(scenario())

    def test_f2_booking_draft_rejects_unissued_and_expired_preview(self):
        with self.assertRaises(Exception) as unissued:
            self.container.actions.create_draft(
                "library.spaces.book", {
                    "preview_digest": "a" * 64,
                    "policy_acceptance_acknowledged": True,
                }
            )
        self.assertEqual(unissued.exception.code, "LIBRARY_BOOKING_PREVIEW_NOT_ISSUED")

        registry = LibraryBookingPreviewRegistry()
        registry.issue("b" * 64, {"expires_at": "2020-01-01T00:00:00+00:00"})
        with self.assertRaises(Exception) as expired:
            registry.require("b" * 64)
        self.assertEqual(expired.exception.code, "LIBRARY_BOOKING_PREVIEW_EXPIRED")

    def test_f2_draft_is_rejected_when_app_is_not_loopback_bound(self):
        async def scenario():
            connector = self.container.connectors["sis_browser"]
            connector.search_library_space_availability = AsyncMock(
                return_value=self.space_navigation()
            )
            preview_task = await self.container.tasks.submit_and_wait(
                "library.spaces.booking_preview",
                {
                    "facility_type": "single_study_room",
                    "date": "2026-09-20",
                    "floor": "4/F",
                    "room": "Study Room A",
                    "start_time": "09:00",
                    "end_time": "10:30",
                    "eligibility_category": "current_hku_students",
                },
            )
            with patch("config.APP_HOST", "0.0.0.0"):
                with self.assertRaises(Exception) as denied:
                    self.container.actions.create_draft(
                        "library.spaces.book", {
                            "preview_digest": preview_task.result["preview_digest"],
                            "policy_acceptance_acknowledged": True,
                        }
                    )
            self.assertEqual(denied.exception.code, "LIBRARY_BOOKING_LOCAL_ONLY")

        asyncio.run(scenario())

    def test_booking_preview_unavailable_is_successful_domain_verdict(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(slots=[], booked_candidates=1)
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json={
                "facility_type": "single_study_room",
                "date": "2026-09-20",
                "room": "Study Room A",
                "start_time": "09:00",
                "end_time": "10:30",
                "eligibility_category": "current_hku_students",
            },
        ).json()
        self.assertTrue(response["ok"])
        self.assertFalse(response["result"]["ready"])
        self.assertEqual(response["result"]["reason"], "slot_not_available")
        self.assertIsNone(response["result"]["preview"])

    def test_booking_preview_rejects_displayed_date_mismatch(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(date="2026-09-21")
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json={
                "facility_type": "single_study_room",
                "date": "2026-09-20",
                "room": "Study Room A",
                "start_time": "09:00",
                "end_time": "10:30",
                "eligibility_category": "current_hku_students",
            },
        ).json()
        self.assertTrue(response["ok"])
        self.assertFalse(response["result"]["ready"])
        self.assertEqual(response["result"]["reason"], "date_mismatch")
        self.assertIsNone(response["result"]["preview_digest"])

    def test_booking_preview_rejects_live_facility_context_mismatch(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(
                location="Chi Wah Learning Commons",
                booking_facility_type="Study Room",
            )
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json={
                "facility_type": "single_study_room",
                "date": "2026-09-20",
                "room": "Study Room A",
                "start_time": "09:00",
                "end_time": "10:30",
                "eligibility_category": "current_hku_students",
            },
        ).json()
        self.assertTrue(response["ok"])
        self.assertFalse(response["result"]["ready"])
        self.assertEqual(response["result"]["reason"], "facility_context_mismatch")
        self.assertIsNone(response["result"]["preview"])

    def test_booking_preview_unsupported_eligibility_does_not_open_browser(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock()
        response = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json={
                "facility_type": "studio_editing_room",
                "date": "2026-09-20",
                "room": "Editing Room A",
                "start_time": "09:00",
                "end_time": "10:00",
                "eligibility_category": "hku_alumni",
            },
        ).json()
        self.assertTrue(response["ok"])
        self.assertFalse(response["result"]["ready"])
        self.assertEqual(response["result"]["reason"], "eligibility_not_supported")
        self.assertFalse(response["result"]["navigation_interactions_performed"])
        connector.search_library_space_availability.assert_not_awaited()

    def test_booking_preview_rejects_invalid_time_range(self):
        response = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json={
                "facility_type": "single_study_room",
                "date": "2026-09-20",
                "room": "Study Room A",
                "start_time": "10:30",
                "end_time": "09:00",
                "eligibility_category": "current_hku_students",
            },
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "INVALID_REQUEST")

    def test_booking_preview_fails_closed_on_ambiguous_exact_match(self):
        connector = self.container.connectors["sis_browser"]
        slot = {
            "floor": "4/F",
            "room": "Study Room A",
            "start_time": "09:00",
            "end_time": "10:30",
            "status": "available",
        }
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(slots=[slot, slot.copy()])
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json={
                "facility_type": "single_study_room",
                "date": "2026-09-20",
                "floor": "4/F",
                "room": "Study Room A",
                "start_time": "09:00",
                "end_time": "10:30",
                "eligibility_category": "current_hku_students",
            },
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "LIBRARY_SPACE_SLOT_AMBIGUOUS")

    def test_booking_preview_fails_closed_on_incomplete_availability_parse(self):
        connector = self.container.connectors["sis_browser"]
        connector.search_library_space_availability = AsyncMock(
            return_value=self.space_navigation(incomplete=1)
        )
        response = self.client.post(
            "/api/v1/integration/library/spaces/booking-preview",
            headers=self.headers,
            json={
                "facility_type": "single_study_room",
                "date": "2026-09-20",
                "room": "Study Room A",
                "start_time": "09:00",
                "end_time": "10:30",
                "eligibility_category": "current_hku_students",
            },
        ).json()
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "LIBRARY_SPACE_PARSE_INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
