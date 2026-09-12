from __future__ import annotations

import asyncio
import json
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "project"
TEST_TEMP_ROOT = ROOT / "tests" / ".tmp"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(PROJECT))

from agents.base import BaseCapability
from agents.models import (
    CapabilityManifest,
    CapabilityMode,
    ConfirmationMode,
    ExecutionContext,
    RiskLevel,
    TaskStatus,
)
from api.app import create_api_app
from application import ApplicationContainer
from agents.knowledge.agent import KnowledgeAnswerCapability
from browser_bridge.models import HeartbeatMessage, SISNavigationResult, SISPageSnapshot
from browser_bridge.service import BrowserBridgeError, BrowserBridgeService
from connectors.sis.protocol import (
    BrowserCommand,
    BrowserCommandName,
    sanitize_for_log,
)
from ui.gradio_app import create_gradio_ui


def preflight_payload(*, visible_class_number: str = "12345") -> dict:
    return {
        "origin": "https://sis-main.hku.hk",
        "logged_in": True,
        "page_kind": "cart",
        "term_label": "2026-27 Sem 1",
        "current_term_label": "2026-27 Sem 1",
        "expected_courses": [
            {"course_code": "COMP2119", "section": "1A", "class_number": "12345"}
        ],
        "visible_courses": [
            {
                "course_code": "COMP2119",
                "section": "1A",
                "class_number": visible_class_number,
            }
        ],
    }


def live_preflight_payload(*, term_label: str = "2026-27 Sem 2") -> dict:
    return {
        "term_label": term_label,
        "expected_courses": [
            {"course_code": "COMP2119", "section": "1A"}
        ],
    }


def live_cart_snapshot(*, term_label: str = "2026-27 Sem 2", courses=None) -> dict:
    return {
        "bound": True,
        "origin": "https://sis-main.hku.hk",
        "logged_in": True,
        "page_kind": "cart",
        "term_label": term_label,
        "course_count": len(courses or []),
        "visible_courses": courses or [],
        "temporary_courses": courses or [],
        "schedule_courses": [],
    }


def navigation_result() -> dict:
    return {
        "read_only": True,
        "navigation_only": True,
        "sis_write_requests_sent": 0,
        "source_origin": "https://studentportal.hku.hk",
        "source_page_kind": "portal_home",
        "target_origin": "https://sis-main.hku.hk",
        "target_page_kind": "cart",
        "steps": [
            "portal_to_sis",
            "sis_fixed_route_to_enrollment_add_classes",
            "sis_select_term",
        ],
        "snapshot": live_cart_snapshot(),
    }


class DummyWriteInput(BaseModel):
    value: str


class DummyWriteCapability(BaseCapability):
    input_model = DummyWriteInput
    manifest = CapabilityManifest(
        id="test.write",
        agent="test",
        title="Test write",
        description="Test-only confirmed write.",
        mode=CapabilityMode.WRITE,
        risk=RiskLevel.HIGH,
        confirmation=ConfirmationMode.EXPLICIT_TWO_PHASE,
        input_schema="DummyWriteInput",
        output_schema="DummyWriteResult",
    )

    async def execute(self, validated_input: DummyWriteInput, context: ExecutionContext) -> dict:
        return {"value": validated_input.value, "executed": True}


class PlatformAPITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT)
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.container = ApplicationContainer(self.db_path)
        self.integration_token = "test-integration-token-" + ("x" * 32)
        self.client = TestClient(
            create_api_app(
                self.container,
                integration_token=self.integration_token,
            )
        )

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def test_health_capabilities_and_connections(self):
        health = self.client.get("/api/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["mode"], "local-first")

        capabilities = self.client.get("/api/v1/capabilities").json()["capabilities"]
        self.assertEqual(
            {item["id"] for item in capabilities},
            {
                "knowledge.answer",
                "sis.enrollment.preflight",
                "sis.enrollment.live_preflight",
                "sis.enrollment.navigate_and_preflight",
                "sis.navigation.open_enrollment_add_classes",
            },
        )
        connections = self.client.get("/api/v1/connections").json()["connections"]
        browser = next(item for item in connections if item["id"] == "sis_browser")
        self.assertEqual(browser["status"], "disconnected")
        self.assertFalse(browser["safe_for_writes"])

    def integration_headers(self, correlation_id: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.integration_token}"}
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        return headers

    def test_integration_api_requires_its_own_bearer_token(self):
        missing = self.client.get("/api/v1/integration/status")
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.headers["www-authenticate"], "Bearer")
        self.assertEqual(missing.json()["error"]["code"], "AUTH_REQUIRED")
        self.assertEqual(missing.json()["api_version"], "v1")

        invalid = self.client.get(
            "/api/v1/integration/status",
            headers={"Authorization": "Bearer " + ("z" * 64)},
        )
        self.assertEqual(invalid.status_code, 403)
        self.assertEqual(invalid.json()["error"]["code"], "AUTH_INVALID")

        status = self.client.get(
            "/api/v1/integration/status",
            headers=self.integration_headers("host-session-123"),
        )
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.headers["x-correlation-id"], "host-session-123")
        body = status.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["read_only"])
        self.assertEqual(body["correlation_id"], "host-session-123")
        self.assertEqual(body["result"]["auth_mode"], "bearer")
        self.assertNotIn(self.integration_token, str(body))

    def test_integration_sync_has_stable_success_and_error_envelopes(self):
        disconnected = self.client.post(
            "/api/v1/integration/sis/sync",
            headers=self.integration_headers(),
        )
        self.assertEqual(disconnected.status_code, 409)
        self.assertFalse(disconnected.json()["ok"])
        self.assertEqual(disconnected.json()["error"]["code"], "BROWSER_NOT_CONNECTED")

        visible = {
            "course_code": "COMP3297",
            "section": "2B",
            "class_number": "1725",
        }
        inspect = AsyncMock(return_value=live_cart_snapshot(courses=[visible]))
        self.container.connectors["sis_browser"].inspect_cart = inspect
        synced = self.client.post(
            "/api/v1/integration/sis/sync",
            headers=self.integration_headers("sync-1"),
        )
        self.assertEqual(synced.status_code, 200)
        body = synced.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["correlation_id"], "sync-1")
        self.assertEqual(body["result"]["temporary_courses"], [visible])
        self.assertEqual(body["result"]["schedule_courses"], [])
        inspect.assert_awaited_once()

    def test_integration_preflight_preserves_business_result_and_correlation(self):
        inspect = AsyncMock(return_value=live_cart_snapshot(courses=[]))
        self.container.connectors["sis_browser"].preflight_snapshot = inspect

        response = self.client.post(
            "/api/v1/integration/sis/preflight",
            headers=self.integration_headers("preflight-1"),
            json=live_preflight_payload(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["result"]["ready"])
        self.assertEqual(body["correlation_id"], "preflight-1")
        self.assertEqual(body["task"]["correlation_id"], "preflight-1")
        self.assertEqual(body["result"]["sis_write_requests_sent"], 0)

    def test_integration_navigation_is_audited_and_accepts_only_term_intent(self):
        navigate = AsyncMock(return_value=navigation_result())
        self.container.connectors["sis_browser"].open_enrollment_add_classes = navigate

        response = self.client.post(
            "/api/v1/integration/sis/navigate",
            headers=self.integration_headers("navigate-1"),
            json={"term_label": "2026-27 Sem 2"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["read_only"])
        self.assertTrue(body["result"]["navigation_only"])
        self.assertEqual(body["result"]["sis_write_requests_sent"], 0)
        self.assertEqual(body["result"]["target_page_kind"], "cart")
        self.assertEqual(body["task"]["correlation_id"], "navigate-1")
        self.assertEqual(body["task"]["capability"], "sis.navigation.open_enrollment_add_classes")
        navigate.assert_awaited_once_with("2026-27 Sem 2")
        audit = self.client.get("/api/v1/audit").json()["events"]
        self.assertTrue(any(item["task_id"] == body["task"]["id"] for item in audit))

    def test_integration_navigation_fails_closed_with_stable_browser_error(self):
        navigate = AsyncMock(
            side_effect=BrowserBridgeError(
                "NAVIGATION_TARGET_AMBIGUOUS",
                "Enrollment Add Classes is ambiguous; navigation stopped safely.",
            )
        )
        self.container.connectors["sis_browser"].open_enrollment_add_classes = navigate

        body = self.client.post(
            "/api/v1/integration/sis/navigate",
            headers=self.integration_headers(),
        ).json()

        self.assertFalse(body["ok"])
        self.assertEqual(body["task"]["status"], "failed")
        self.assertEqual(body["error"]["code"], "NAVIGATION_TARGET_AMBIGUOUS")
        self.assertIsNone(body["result"])

    def test_integration_navigation_rejects_invalid_term_label(self):
        response = self.client.post(
            "/api/v1/integration/sis/navigate",
            headers=self.integration_headers("navigate-invalid"),
            json={"term_label": "Sem 2"},
        )

        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "INVALID_REQUEST")

    def test_integration_navigate_and_preflight_composes_one_read_only_task(self):
        visible = {
            "course_code": "COMP2119",
            "section": "1A",
            "class_number": "12345",
        }
        navigation = navigation_result()
        navigation["snapshot"] = live_cart_snapshot(courses=[visible])
        bind = AsyncMock(
            return_value={
                "origin": "https://studentportal.hku.hk",
                "page_kind": "portal_home",
                "logged_in": True,
            }
        )
        navigate = AsyncMock(return_value=navigation)
        self.container.connectors["sis_browser"].bind_hku_tab = bind
        self.container.connectors["sis_browser"].open_enrollment_add_classes = navigate

        response = self.client.post(
            "/api/v1/integration/sis/navigate-and-preflight",
            headers=self.integration_headers("combined-1"),
            json=live_preflight_payload(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["read_only"])
        self.assertEqual(
            body["task"]["capability"], "sis.enrollment.navigate_and_preflight"
        )
        self.assertEqual(body["task"]["correlation_id"], "combined-1")
        self.assertTrue(body["result"]["ready"])
        self.assertEqual(body["result"]["sis_write_requests_sent"], 0)
        self.assertTrue(body["result"]["navigation_interactions_performed"])
        self.assertTrue(body["result"]["term_selection_performed"])
        self.assertEqual(body["result"]["enrollment_writes_performed"], 0)
        self.assertEqual(
            body["result"]["binding"]["origin"], "https://studentportal.hku.hk"
        )
        self.assertEqual(
            body["result"]["navigation"]["steps"],
            [
                "portal_to_sis",
                "sis_fixed_route_to_enrollment_add_classes",
                "sis_select_term",
            ],
        )
        self.assertEqual(body["result"]["course_lists"]["temporary_courses"], [visible])
        self.assertEqual(body["result"]["preflight"]["matched_courses"], [visible])
        bind.assert_awaited_once_with()
        navigate.assert_awaited_once_with("2026-27 Sem 2")

    def test_integration_navigate_and_preflight_preserves_domain_mismatch(self):
        bind = AsyncMock(
            return_value={
                "origin": "https://studentportal.hku.hk",
                "page_kind": "portal_home",
                "logged_in": True,
            }
        )
        navigate = AsyncMock(return_value=navigation_result())
        self.container.connectors["sis_browser"].bind_hku_tab = bind
        self.container.connectors["sis_browser"].open_enrollment_add_classes = navigate

        response = self.client.post(
            "/api/v1/integration/sis/navigate-and-preflight",
            headers=self.integration_headers("combined-mismatch"),
            json=live_preflight_payload(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["result"]["ready"])
        self.assertFalse(body["result"]["preflight"]["ready"])
        self.assertEqual(
            body["result"]["preflight"]["missing_courses"],
            [{"course_code": "COMP2119", "section": "1A"}],
        )
        self.assertEqual(body["result"]["sis_write_requests_sent"], 0)

    def test_combined_preflight_reports_no_navigation_when_target_is_already_open(self):
        bind = AsyncMock(return_value=live_cart_snapshot())
        navigation = navigation_result()
        navigation["source_origin"] = "https://sis-main.hku.hk"
        navigation["source_page_kind"] = "cart"
        navigation["steps"] = ["target_already_open"]
        navigate = AsyncMock(return_value=navigation)
        self.container.connectors["sis_browser"].bind_hku_tab = bind
        self.container.connectors["sis_browser"].open_enrollment_add_classes = navigate

        response = self.client.post(
            "/api/v1/integration/sis/navigate-and-preflight",
            headers=self.integration_headers("combined-already-open"),
            json=live_preflight_payload(),
        )

        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["result"]["navigation_interactions_performed"])
        self.assertFalse(body["result"]["term_selection_performed"])
        self.assertEqual(body["result"]["enrollment_writes_performed"], 0)

    def test_combined_preflight_explains_rejected_pairing_token(self):
        self.container.connectors["sis_browser"].bind_hku_tab = AsyncMock(
            side_effect=BrowserBridgeError(
                "PAIRING_TOKEN_REJECTED",
                "The browser extension pairing token was rejected.",
            )
        )

        response = self.client.post(
            "/api/v1/integration/sis/navigate-and-preflight",
            headers=self.integration_headers("combined-token-rejected"),
            json=live_preflight_payload(),
        )

        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "PAIRING_TOKEN_REJECTED")
        self.assertIn("Connections", body["error"]["recovery"])
        self.assertIn("Save and connect", body["error"]["recovery"])

    def test_integration_validation_errors_use_the_versioned_envelope(self):
        payload = live_preflight_payload()
        payload["expected_courses"][0]["class_number"] = "12345"
        response = self.client.post(
            "/api/v1/integration/sis/preflight",
            headers=self.integration_headers("invalid-1"),
            json=payload,
        )

        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["api_version"], "v1")
        self.assertEqual(body["correlation_id"], "invalid-1")
        self.assertEqual(body["error"]["code"], "INVALID_REQUEST")

    def test_browser_pairing_requires_extension_origin_and_current_token(self):
        self.assertEqual(
            self.client.get("/api/v1/browser/pairing", headers={"host": "evil.example"}).status_code,
            400,
        )
        rejected_rotation = self.client.post(
            "/api/v1/browser/pairing/rotate",
            headers={"origin": "https://evil.example"},
        )
        self.assertEqual(rejected_rotation.status_code, 403)
        self.assertEqual(
            rejected_rotation.json()["detail"]["code"], "PAIRING_ORIGIN_REJECTED"
        )
        pairing = self.client.get("/api/v1/browser/pairing").json()
        self.assertGreaterEqual(len(pairing["pairing_token"]), 20)
        self.assertEqual(pairing["websocket_url"], "ws://testserver/api/v1/browser/ws")

        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/api/v1/browser/ws", headers={"origin": "https://evil.example"}
            ):
                pass

        with self.client.websocket_connect(
            "/api/v1/browser/ws",
            headers={"origin": f"chrome-extension://{'a' * 32}"},
        ) as invalid_token_socket:
            invalid_token_socket.send_json(
                {"type": "pair", "token": "x" * 32, "extension_version": "0.1.0"}
            )
            with self.assertRaises(WebSocketDisconnect):
                invalid_token_socket.receive_json()

        extension_id = "a" * 32
        with self.client.websocket_connect(
            "/api/v1/browser/ws",
            headers={"origin": f"chrome-extension://{extension_id}"},
        ) as websocket:
            websocket.send_json(
                {
                    "type": "pair",
                    "token": pairing["pairing_token"],
                    "extension_version": "0.1.0",
                }
            )
            paired = websocket.receive_json()
            self.assertTrue(paired["read_only"])
            self.assertEqual(paired["extension_id"], extension_id)
            self.assertEqual(
                self.client.get("/api/v1/browser/status").json()["lifecycle_state"],
                "paired",
            )
            websocket.send_json(
                {
                    "type": "heartbeat",
                    "tab": {
                        "bound": True,
                        "origin": "https://studentportal.hku.hk",
                        "logged_in": True,
                        "page_kind": "portal_home",
                        "term_label": None,
                        "course_count": 0,
                    },
                }
            )
            portal_status = self.client.get("/api/v1/browser/status").json()
            self.assertEqual(portal_status["lifecycle_state"], "portal_bound")
            websocket.send_json(
                {
                    "type": "heartbeat",
                    "tab": {
                        "bound": True,
                        "origin": "https://sis-main.hku.hk",
                        "logged_in": True,
                        "page_kind": "cart",
                        "term_label": "2026-27 Sem 1",
                        "course_count": 1,
                    },
                }
            )
            status = self.client.get("/api/v1/browser/status").json()
            self.assertEqual(status["status"], "connected")
            self.assertEqual(status["lifecycle_state"], "sis_bound")
            self.assertEqual(status["tab"]["page_kind"], "cart")

        self.assertEqual(self.client.get("/api/v1/browser/status").json()["status"], "disconnected")

        rotated = self.client.post("/api/v1/browser/pairing/rotate").json()
        self.assertEqual(rotated["pairing_token_source"], "runtime_rotated")
        self.assertFalse(rotated["persistent_across_restarts"])
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/api/v1/browser/ws",
                headers={"origin": f"chrome-extension://{extension_id}"},
            ) as old_token_socket:
                old_token_socket.send_json(
                    {
                        "type": "pair",
                        "token": pairing["pairing_token"],
                        "extension_version": "0.5.0",
                    }
                )
                old_token_socket.receive_json()
        rejected_status = self.client.get("/api/v1/browser/status").json()
        self.assertEqual(rejected_status["lifecycle_state"], "token_rejected")
        rejected_bind = self.client.post("/api/v1/browser/sis/bind")
        self.assertEqual(rejected_bind.json()["detail"]["code"], "PAIRING_TOKEN_REJECTED")

        with self.client.websocket_connect(
            "/api/v1/browser/ws",
            headers={"origin": f"chrome-extension://{extension_id}"},
        ) as rotated_socket:
            rotated_socket.send_json(
                {
                    "type": "pair",
                    "token": rotated["pairing_token"],
                    "extension_version": "0.5.0",
                }
            )
            self.assertEqual(rotated_socket.receive_json()["type"], "paired")

        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/api/v1/browser/ws",
                headers={"origin": f"chrome-extension://{'b' * 32}"},
            ):
                pass

        revoked = self.client.post("/api/v1/browser/pairing/revoke").json()
        self.assertTrue(revoked["extension_pin_cleared"])
        self.assertEqual(revoked["pairing_token_source"], "runtime_revoked")
        with self.client.websocket_connect(
            "/api/v1/browser/ws",
            headers={"origin": f"chrome-extension://{'b' * 32}"},
        ) as replacement_socket:
            replacement_socket.send_json(
                {
                    "type": "pair",
                    "token": revoked["pairing_token"],
                    "extension_version": "0.5.0",
                }
            )
            self.assertEqual(replacement_socket.receive_json()["type"], "paired")

        bind = self.client.post("/api/v1/browser/sis/bind")
        self.assertEqual(bind.status_code, 409)
        self.assertEqual(bind.json()["detail"]["code"], "BROWSER_NOT_CONNECTED")

    def test_configured_pairing_token_is_stable_across_service_instances(self):
        token = "stable-browser-pairing-token-" + ("x" * 32)
        first = BrowserBridgeService(
            pairing_token=token,
            pairing_token_source="environment",
        )
        second = BrowserBridgeService(
            pairing_token=token,
            pairing_token_source="environment",
        )

        first_info = first.pairing_info("ws://127.0.0.1:7860/api/v1/browser/ws")
        second_info = second.pairing_info("ws://127.0.0.1:7860/api/v1/browser/ws")
        self.assertEqual(first_info["pairing_token"], second_info["pairing_token"])
        self.assertEqual(first_info["pairing_token_source"], "environment")
        self.assertTrue(first_info["persistent_across_restarts"])
        with self.assertRaises(ValueError):
            BrowserBridgeService(pairing_token="too-short")

    def test_simulated_sis_preflight_is_zero_request_and_exact(self):
        response = self.client.post("/api/v1/sis/preflight", json=preflight_payload())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["task"]["status"], "completed")
        self.assertTrue(body["result"]["ok"])
        self.assertTrue(body["result"]["simulated"])
        self.assertTrue(body["result"]["no_requests_sent"])

        mismatch = self.client.post(
            "/api/v1/sis/preflight", json=preflight_payload(visible_class_number="99999")
        ).json()["result"]
        self.assertFalse(mismatch["ok"])
        self.assertEqual(len(mismatch["missing"]), 1)
        self.assertEqual(len(mismatch["unexpected"]), 1)

    def test_live_sis_preflight_matches_the_browser_cart(self):
        expected_course = live_preflight_payload()["expected_courses"][0]
        visible_course = {**expected_course, "class_number": "12345"}
        inspect = AsyncMock(return_value=live_cart_snapshot(courses=[visible_course]))
        self.container.connectors["sis_browser"].preflight_snapshot = inspect

        response = self.client.post(
            "/api/v1/browser/sis/preflight", json=live_preflight_payload()
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["task"]["status"], "completed")
        self.assertTrue(body["result"]["ready"])
        self.assertTrue(body["result"]["term_match"])
        self.assertEqual(body["result"]["comparison_fields"], ["course_code", "section"])
        self.assertEqual(body["result"]["matched_courses"], [visible_course])
        self.assertFalse(body["result"]["simulated"])
        self.assertEqual(body["result"]["sis_write_requests_sent"], 0)
        inspect.assert_awaited_once()

    def test_live_sis_preflight_reports_empty_cart_and_wrong_term(self):
        inspect = AsyncMock(return_value=live_cart_snapshot(term_label="2026-27 Sem 1"))
        self.container.connectors["sis_browser"].preflight_snapshot = inspect

        result = self.client.post(
            "/api/v1/browser/sis/preflight", json=live_preflight_payload()
        ).json()["result"]

        self.assertFalse(result["ready"])
        self.assertFalse(result["term_match"])
        self.assertEqual(len(result["missing_courses"]), 1)
        self.assertEqual(result["unexpected_courses"], [])
        self.assertIn("Current SIS term does not match", " ".join(result["issues"]))

    def test_live_sis_preflight_rejects_ambiguous_class_numbers(self):
        expected = live_preflight_payload()["expected_courses"][0]
        courses = [
            {**expected, "class_number": "12345"},
            {**expected, "class_number": "67890"},
        ]
        inspect = AsyncMock(return_value=live_cart_snapshot(courses=courses))
        self.container.connectors["sis_browser"].preflight_snapshot = inspect

        result = self.client.post(
            "/api/v1/browser/sis/preflight", json=live_preflight_payload()
        ).json()["result"]

        self.assertFalse(result["ready"])
        self.assertEqual(len(result["duplicate_visible_courses"]), 2)
        self.assertIn("more than one class number", " ".join(result["issues"]))

    def test_live_sis_preflight_preserves_browser_error_codes(self):
        inspect = AsyncMock(
            side_effect=BrowserBridgeError(
                "WRONG_SIS_PAGE", "Open the Temporary Course List before inspecting the cart."
            )
        )
        self.container.connectors["sis_browser"].preflight_snapshot = inspect

        body = self.client.post(
            "/api/v1/browser/sis/preflight", json=live_preflight_payload()
        ).json()

        self.assertEqual(body["task"]["status"], "failed")
        self.assertIsNone(body["result"])
        self.assertEqual(body["task"]["error"]["code"], "WRONG_SIS_PAGE")

    def test_tasks_events_and_audit_are_persisted(self):
        task_id = self.client.post("/api/v1/sis/preflight", json=preflight_payload()).json()[
            "task"
        ]["id"]
        task = self.client.get(f"/api/v1/tasks/{task_id}").json()
        self.assertEqual(task["status"], "completed")
        events = self.container.store.list_task_events(task_id)
        self.assertEqual(events[0].event_type, "task.queued")
        self.assertEqual(events[-1].event_type, "task.completed")
        with self.client.stream("GET", f"/api/v1/tasks/{task_id}/events") as stream:
            event_stream = "".join(stream.iter_text())
        self.assertIn("event: task.completed", event_stream)
        audit = self.client.get("/api/v1/audit").json()["events"]
        self.assertTrue(any(item["task_id"] == task_id for item in audit))

    def test_knowledge_task_content_is_not_persisted(self):
        task = self.container.tasks.create(
            "knowledge.answer",
            {"message": "private question", "history": [{"role": "user", "content": "secret"}]},
        )
        stored = self.container.store.get_task(task.id)
        self.assertEqual(stored.input["message"], "[REDACTED]")
        self.assertNotIn("private question", str(stored.input))
        self.assertNotIn("secret", str(stored.input))

    def test_invalid_term_is_rejected_at_api_boundary(self):
        payload = preflight_payload()
        payload["term_label"] = "Sem 1"
        response = self.client.post("/api/v1/sis/preflight", json=payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_invalid_live_section_is_rejected_at_api_boundary(self):
        payload = live_preflight_payload()
        payload["expected_courses"][0]["section"] = "1A / invalid"

        response = self.client.post("/api/v1/browser/sis/preflight", json=payload)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")

    def test_live_preflight_rejects_user_supplied_class_number(self):
        payload = live_preflight_payload()
        payload["expected_courses"][0]["class_number"] = "12345"

        response = self.client.post("/api/v1/browser/sis/preflight", json=payload)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")


class SafetyFrameworkTests(unittest.TestCase):
    def test_browser_bridge_named_command_round_trip(self):
        class FakeWebSocket:
            def __init__(self):
                self.sent = asyncio.Queue()

            async def send_json(self, payload):
                await self.sent.put(payload)

        async def scenario():
            bridge = BrowserBridgeService(command_timeout=1)
            websocket = FakeWebSocket()
            await bridge._activate_connection(websocket, "b" * 32, "0.1.0")
            request_task = asyncio.create_task(
                bridge.request(BrowserCommand(command=BrowserCommandName.INSPECT_PAGE))
            )
            sent = await websocket.sent.get()
            self.assertEqual(sent["command"], "sis.inspect_page")
            await bridge._handle_message(
                {
                    "protocol_version": 1,
                    "request_id": sent["request_id"],
                    "ok": True,
                    "data": {"page_kind": "unknown"},
                    "error": None,
                }
            )
            result = await request_task
            self.assertTrue(result.ok)
            self.assertEqual(result.data["page_kind"], "unknown")

        asyncio.run(scenario())

    def test_browser_bridge_routes_gui_requests_to_the_websocket_event_loop(self):
        class ThreadSafeWebSocket:
            def __init__(self):
                self.sent = queue.Queue()

            async def send_json(self, payload):
                self.sent.put(payload)

        bridge = BrowserBridgeService(command_timeout=1)
        websocket = ThreadSafeWebSocket()
        owner_loop = asyncio.new_event_loop()
        owner_ready = threading.Event()

        def run_owner_loop():
            asyncio.set_event_loop(owner_loop)
            owner_ready.set()
            owner_loop.run_forever()
            owner_loop.close()

        owner_thread = threading.Thread(target=run_owner_loop)
        owner_thread.start()
        self.assertTrue(owner_ready.wait(timeout=1))
        asyncio.run_coroutine_threadsafe(
            bridge._activate_connection(websocket, "c" * 32, "0.1.0"), owner_loop
        ).result(timeout=1)

        async def gui_loop_scenario():
            request_task = asyncio.create_task(
                bridge.request(BrowserCommand(command=BrowserCommandName.INSPECT_PAGE))
            )
            sent = await asyncio.to_thread(websocket.sent.get, True, 1)
            response = {
                "protocol_version": 1,
                "request_id": sent["request_id"],
                "ok": True,
                "data": {"page_kind": "unknown"},
                "error": None,
            }
            owner_result = asyncio.run_coroutine_threadsafe(
                bridge._handle_message(response), owner_loop
            )
            await asyncio.wrap_future(owner_result)
            return await request_task

        try:
            result = asyncio.run(gui_loop_scenario())
            self.assertTrue(result.ok)
            self.assertEqual(bridge.status()["last_command"]["stage"], "completed")
        finally:
            owner_loop.call_soon_threadsafe(owner_loop.stop)
            owner_thread.join(timeout=2)

    def test_bridge_messages_reject_unexpected_sensitive_fields(self):
        with self.assertRaises(Exception):
            HeartbeatMessage.model_validate(
                {"type": "heartbeat", "tab": None, "cookie": "must-not-enter-bridge"}
            )
        with self.assertRaises(Exception):
            SISNavigationResult.model_validate(
                {**navigation_result(), "sis_write_requests_sent": 1}
            )
        with self.assertRaises(Exception):
            SISPageSnapshot.model_validate(
                {
                    "diagnostics": {
                        "parser_version": "0.2.0",
                        "document_count": 1,
                        "table_count": 1,
                        "row_count": 1,
                        "cart_marker_found": True,
                        "schedule_marker_found": True,
                        "temporary_candidate_count": 0,
                        "schedule_candidate_count": 0,
                        "unclassified_candidate_count": 0,
                        "unclassified_courses": [],
                        "cookie": "must-not-enter-diagnostics",
                    }
                }
            )

    def test_extension_manifest_is_read_only_and_parser_handles_synthetic_row(self):
        extension_root = ROOT / "browser_runtime" / "extension"
        manifest = json.loads((extension_root / "manifest.json").read_text(encoding="utf-8"))
        permissions = set(manifest["permissions"])
        self.assertTrue(
            permissions.isdisjoint(
                {
                    "cookies",
                    "debugger",
                    "downloads",
                    "webRequest",
                    "clipboardRead",
                    "scripting",
                    "tabs",
                }
            )
        )
        content_matches = {
            match
            for content_script in manifest["content_scripts"]
            for match in content_script["matches"]
        }
        self.assertEqual(
            content_matches,
            {
                "https://hkuportal.hku.hk/*",
                "https://studentportal.hku.hk/*",
                "https://sis-main.hku.hk/*",
            },
        )
        sis_content_script = next(
            item
            for item in manifest["content_scripts"]
            if item["matches"] == ["https://sis-main.hku.hk/*"]
        )
        self.assertEqual(sis_content_script["run_at"], "document_start")
        self.assertEqual(
            manifest["host_permissions"],
            [
                "https://hkuportal.hku.hk/*",
                "https://studentportal.hku.hk/*",
                "https://sis-main.hku.hk/*",
                "http://127.0.0.1/*",
            ],
        )

        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is not installed; skipped pure parser test.")
        result = subprocess.run(
            [node, str(ROOT / "tests" / "sis_parser.test.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        navigation_result_process = subprocess.run(
            [node, str(ROOT / "tests" / "navigation.test.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            navigation_result_process.returncode,
            0,
            navigation_result_process.stderr or navigation_result_process.stdout,
        )
        lifecycle_result_process = subprocess.run(
            [node, str(ROOT / "tests" / "connection_lifecycle.test.js")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            lifecycle_result_process.returncode,
            0,
            lifecycle_result_process.stderr or lifecycle_result_process.stdout,
        )

    def test_knowledge_initialization_starts_once_in_the_background(self):
        capability = KnowledgeAnswerCapability()
        started = threading.Event()
        release = threading.Event()

        def fake_initialize():
            started.set()
            release.wait(timeout=2)
            capability._set_initialization_state(
                status="ready",
                progress=1.0,
                description="Knowledge agent is ready",
            )

        with patch.object(capability, "initialize", side_effect=fake_initialize) as initialize:
            first = capability.start_initialize()
            self.assertTrue(started.wait(timeout=1))
            second = capability.start_initialize()
            release.set()

            for _ in range(100):
                if capability.initialization_snapshot()["status"] == "ready":
                    break
                threading.Event().wait(0.01)

        self.assertEqual(first["status"], "initializing")
        self.assertEqual(second["status"], "initializing")
        self.assertEqual(capability.initialization_snapshot()["status"], "ready")
        initialize.assert_called_once_with()

    def test_gui_has_only_the_explicit_nonblocking_chat_select_handler(self):
        with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
            container = ApplicationContainer(Path(temp_dir) / "test.db")
            gui = create_gradio_ui(container)
            gui_config = gui.get_config_file()
            gui.close()

        load_events = [
            target
            for dependency in gui_config["dependencies"]
            for target in dependency["targets"]
            if target[1] == "load"
        ]
        select_handlers = [
            dependency
            for dependency in gui_config["dependencies"]
            if any(target[1] == "select" for target in dependency["targets"])
        ]

        self.assertEqual(load_events, [])
        self.assertEqual(len(select_handlers), 1)
        self.assertEqual(select_handlers[0]["api_name"], "initialize_chat")
        self.assertFalse(select_handlers[0]["queue"])
        self.assertEqual(select_handlers[0]["show_progress"], "hidden")
        self.assertEqual(select_handlers[0]["api_visibility"], "private")

    def test_named_browser_protocol_and_redaction(self):
        command = BrowserCommand(command=BrowserCommandName.PREFLIGHT)
        self.assertEqual(command.protocol_version, 1)
        navigation_command = BrowserCommand(
            command=BrowserCommandName.OPEN_ENROLLMENT_ADD_CLASSES,
            payload={"term_label": "2026-27 Sem 2"},
        )
        self.assertEqual(navigation_command.payload, {"term_label": "2026-27 Sem 2"})
        redacted = sanitize_for_log(
            {
                "cookie": "secret",
                "integration_api_token": "host-secret",
                "pairing_token": "browser-secret",
                "nested": {"access_token": "token", "safe": "value"},
            }
        )
        self.assertEqual(redacted["cookie"], "[REDACTED]")
        self.assertEqual(redacted["integration_api_token"], "[REDACTED]")
        self.assertEqual(redacted["pairing_token"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["access_token"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["safe"], "value")

    def test_high_risk_write_requires_one_time_confirmation(self):
        async def scenario():
            with tempfile.TemporaryDirectory(dir=TEST_TEMP_ROOT) as temp_dir:
                container = ApplicationContainer(Path(temp_dir) / "test.db")
                container.registry.register(DummyWriteCapability())
                draft = container.actions.create_draft("test.write", {"value": "approved"})
                self.assertEqual(draft.status, TaskStatus.AWAITING_CONFIRMATION)

                with self.assertRaises(Exception):
                    container.actions.execute(
                        draft.id, confirmation_token=None, session_id="test-user"
                    )

                confirmed, token = container.actions.confirm(draft.id, draft.preview_digest)
                self.assertEqual(confirmed.status, TaskStatus.QUEUED)
                task = container.actions.execute(
                    draft.id, confirmation_token=token, session_id="test-user"
                )
                await container.tasks._running[task.id]
                completed = container.store.get_task(task.id)
                self.assertEqual(completed.status, TaskStatus.COMPLETED)
                self.assertTrue(completed.result["executed"])

                with self.assertRaises(Exception):
                    container.actions.execute(
                        draft.id, confirmation_token=token, session_id="test-user"
                    )

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
