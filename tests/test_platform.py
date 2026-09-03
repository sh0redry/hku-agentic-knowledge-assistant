from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import BaseModel


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
from connectors.sis.protocol import BrowserCommand, BrowserCommandName, sanitize_for_log
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
            {"knowledge.answer", "sis.enrollment.preflight"},
        )
        connections = self.client.get("/api/v1/connections").json()["connections"]
        browser = next(item for item in connections if item["id"] == "sis_browser")
        self.assertEqual(browser["status"], "not_implemented")
        self.assertFalse(browser["safe_for_writes"])

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


class SafetyFrameworkTests(unittest.TestCase):
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
