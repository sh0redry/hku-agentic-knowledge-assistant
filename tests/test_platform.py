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
from browser_bridge.models import HeartbeatMessage
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
        self.client = TestClient(create_api_app(self.container))

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
            },
        )
        connections = self.client.get("/api/v1/connections").json()["connections"]
        browser = next(item for item in connections if item["id"] == "sis_browser")
        self.assertEqual(browser["status"], "disconnected")
        self.assertFalse(browser["safe_for_writes"])

    def test_browser_pairing_requires_extension_origin_and_current_token(self):
        self.assertEqual(
            self.client.get("/api/v1/browser/pairing", headers={"host": "evil.example"}).status_code,
            400,
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
            self.assertEqual(status["tab"]["page_kind"], "cart")

        self.assertEqual(self.client.get("/api/v1/browser/status").json()["status"], "disconnected")
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(
                "/api/v1/browser/ws",
                headers={"origin": f"chrome-extension://{'b' * 32}"},
            ):
                pass

        bind = self.client.post("/api/v1/browser/sis/bind")
        self.assertEqual(bind.status_code, 409)
        self.assertEqual(bind.json()["detail"]["code"], "BROWSER_NOT_CONNECTED")

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
        self.assertEqual(
            manifest["content_scripts"][0]["matches"], ["https://sis-main.hku.hk/*"]
        )
        self.assertEqual(
            manifest["host_permissions"],
            ["https://sis-main.hku.hk/*", "http://127.0.0.1/*"],
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
        redacted = sanitize_for_log(
            {"cookie": "secret", "nested": {"access_token": "token", "safe": "value"}}
        )
        self.assertEqual(redacted["cookie"], "[REDACTED]")
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
