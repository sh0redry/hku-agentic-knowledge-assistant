from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "project"))
from fastapi.testclient import TestClient
from api.app import create_api_app
from application import ApplicationContainer
from agents.models import TaskStatus


class LibraryDesktopOperatorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / "tests")
        self.container = ApplicationContainer(Path(self.directory.name) / "test.db")
        self.token = "operator-test-" + "x" * 40
        self.client = TestClient(create_api_app(self.container, integration_token=self.token),
                                 client=("127.0.0.1", 1234))
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.client.close()
        self.directory.cleanup()

    def call(self, op, body=None, **kwargs):
        return self.client.post("/api/v1/integration/library/operator", headers=self.headers,
                                json={"operation": op, "input": body or {}}, **kwargs)

    def test_auth_local_and_operation_allowlist(self):
        path = "/api/v1/integration/library/operator"
        self.assertEqual(self.client.post(path, json={"operation": "shadow_status", "input": {}}).status_code, 401)
        self.assertEqual(self.call("shadow_status").status_code, 200)
        with patch("api.library_operator.library_booking_host_is_loopback", return_value=False):
            self.assertEqual(self.call("shadow_status").status_code, 403)
        self.assertEqual(self.client.post(path, headers={**self.headers, "Origin": "https://evil.example"},
            json={"operation": "shadow_status", "input": {}}).status_code, 403)
        for op, data in [("http_proxy", {"url": "https://evil.example"}), ("shadow_status", {"url": "x"}),
                         ("booking_execute", {"id": "bad", "preview_digest": "a" * 64, "exact_booking_acknowledged": True})]:
            self.assertEqual(self.call(op, data).status_code, 422)
        self.assertEqual(self.client.post(path, headers=self.headers, content="x" * 16385).status_code, 413)

    def test_f1_uses_only_the_named_read_capability(self):
        task = SimpleNamespace(id="test-task", status=TaskStatus.COMPLETED, result={"offered_dates": ["2026-10-03"]})
        self.container.tasks.submit_and_wait = AsyncMock(return_value=task)
        response = self.call("dates", {"facility_type": "discussion_room"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["task_id"], "test-task")
        self.assertEqual(self.container.tasks.submit_and_wait.call_args.args[0], "library.spaces.list_dates")

    def test_f2_explicit_confirmation_and_repeat_submission_refusal(self):
        identifier = "12345678-1234-1234-1234-123456789abc"
        draft = SimpleNamespace(id=identifier, capability="library.spaces.book", status=TaskStatus.AWAITING_CONFIRMATION)
        actions = SimpleNamespace(confirm=Mock(return_value=(draft, "secret-one-time-token")), execute=Mock())
        def execute(*args, **kwargs):
            self.assertEqual(kwargs["confirmation_token"], "secret-one-time-token")
            draft.status = TaskStatus.RUNNING
            return SimpleNamespace(id=identifier, status=TaskStatus.RUNNING, phase="running")
        actions.execute.side_effect = execute
        self.container.actions = actions
        self.container.store.get_draft_with_token_hash = Mock(return_value=(draft, None))
        payload = {"id": identifier, "preview_digest": "a" * 64, "exact_booking_acknowledged": True}
        self.assertEqual(self.call("booking_execute", {**payload, "exact_booking_acknowledged": False}).status_code, 422)
        response = self.call("booking_execute", payload)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("secret-one-time-token", response.text)
        self.assertFalse(response.json()["result"]["booking_success_verified"])
        self.assertEqual(self.call("booking_execute", payload).status_code, 409)
        self.assertEqual(actions.execute.call_count, 1)

    def test_f3_revoke_needs_ack_and_cannot_resume_f4(self):
        identifier = "12345678-1234-1234-1234-123456789abc"
        self.container.library_shadow.change_rule_state = Mock(return_value={"state": "revoked"})
        self.assertEqual(self.call("shadow_action", {"id": identifier, "action": "revoke"}).status_code, 409)
        self.container.library_shadow.change_rule_state.assert_not_called()
        self.assertEqual(self.call("shadow_action", {"id": identifier, "action": "revoke", "revoke_acknowledged": True}).status_code, 200)
        self.assertEqual(self.call("f4_authorization_action", {"id": identifier, "action": "resume"}).status_code, 422)

    def test_f4_pending_state_is_not_execution(self):
        self.container.library_autobook_executor.list = Mock(return_value={
            "execution_enabled": False, "authorization_count": 1,
            "authorizations": [{"state": "pending_executor", "execution_enabled": False, "next_run_at": None}]})
        value = self.call("f4_authorizations").json()
        self.assertFalse(value["execution_enabled"])
        self.assertIsNone(value["result"]["authorizations"][0]["next_run_at"])

    def test_runtime_enablement_requires_ack_and_no_model_tool_is_added(self):
        self.assertEqual(self.call("f4_executor_configure", {"enabled": True, "dry_run": True}).status_code, 422)
        self.container.library_autobook._require_protection = Mock()
        value = self.call("f4_executor_configure", {"enabled": True, "dry_run": True, "operator_acknowledged": True})
        self.assertEqual(value.status_code, 200)
        self.assertTrue(value.json()["execution_enabled"])
        self.assertTrue(value.json()["result"]["dry_run"])
        self.assertEqual(self.call("f4_authorization_arm", {"id": "12345678-1234-1234-1234-123456789abc"}).status_code, 422)
        self.assertNotIn("library.autobook.execute", [m.id for m in self.container.registry.manifests()])


if __name__ == "__main__":
    unittest.main()
