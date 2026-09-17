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


class PortalNoticeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=ROOT / "tests" / ".tmp")
        self.container = ApplicationContainer(Path(self.temp_dir.name) / "test.db")
        self.token = "portal-test-token-" + "x" * 32
        self.client = TestClient(
            create_api_app(self.container, integration_token=self.token)
        )
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def snapshot(self, *, unparsed: int = 0) -> dict:
        return {
            "origin": "https://studentportal.hku.hk",
            "logged_in": True,
            "page_kind": "portal_home",
            "notices": [{
                "title": "Closure of Registry Service Counter",
                "published_date": "2026-06-29",
                "source_label": "General Services of the Registry",
                "url": "https://studentportal.hku.hk/news/registry-counter",
                "url_query_redacted": False,
            }],
            "diagnostics": {
                "parser_version": "0.1.3",
                "news_marker_found": True,
                "notice_candidate_count": 1 + unparsed,
                "parsed_notice_count": 1,
                "unparsed_notice_candidate_count": unparsed,
                "unsafe_notice_url_candidate_count": 0,
                "duplicate_notice_candidate_count": 0,
            },
        }

    def test_visible_notices_are_cached_but_not_persisted(self):
        connector = self.container.connectors["sis_browser"]
        connector.list_portal_notices = AsyncMock(return_value=self.snapshot())

        response = self.client.post(
            "/api/v1/integration/portal/notices/list",
            headers=self.headers,
            json={},
        ).json()

        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertFalse(result["navigation_interactions_performed"])
        self.assertEqual(result["portal_writes_performed"], 0)
        self.assertEqual(result["notice_detail_pages_opened"], 0)
        self.assertEqual(result["notice_list"]["notice_count"], 1)
        self.assertEqual(
            self.container.portal_notices.snapshot()["notices"][0]["title"],
            "Closure of Registry Service Counter",
        )

        stored = self.container.store.get_task(response["task"]["id"])
        self.assertFalse(stored.result["private_notice_details_persisted"])
        self.assertNotIn("Closure of Registry", str(stored.result))
        self.assertNotIn("notice_list", stored.result)

    def test_incomplete_parse_fails_closed_without_replacing_cache(self):
        connector = self.container.connectors["sis_browser"]
        connector.list_portal_notices = AsyncMock(return_value=self.snapshot(unparsed=1))

        response = self.client.post(
            "/api/v1/integration/portal/notices/list",
            headers=self.headers,
            json={},
        ).json()

        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "PORTAL_NOTICE_PARSE_INCOMPLETE")
        self.assertIsNone(self.container.portal_notices.snapshot())


if __name__ == "__main__":
    unittest.main()
