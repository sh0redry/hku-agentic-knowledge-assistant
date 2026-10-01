from __future__ import annotations

import json
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))
from services.local_credentials import LocalCredentialError, load_tokens, publish_tokens
from browser_bridge.service import BrowserBridgeService, BrowserBridgeError


@unittest.skipUnless(sys.platform == "win32", "Windows DPAPI integration")
class LocalCredentialsTests(unittest.TestCase):
    def test_protected_restart_reuse_and_origin_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connection-v1.json"
            token, pairing = "test-integration-" + "x" * 32, "test-pairing-" + "y" * 32
            publish_tokens("http://127.0.0.1:7860", token, pairing, path=path)
            self.assertNotIn(token, path.read_text())
            self.assertNotIn(pairing, path.read_text())
            self.assertEqual(load_tokens("http://127.0.0.1:7860", path=path), {"integration": token, "browser_pairing": pairing})
            self.assertEqual(load_tokens("http://127.0.0.1:9999", path=path), {})
            saved = json.loads(path.read_text())
            saved["integration"] = "AAAA"
            path.write_text(json.dumps(saved))
            with self.assertRaises(LocalCredentialError):
                load_tokens("http://127.0.0.1:7860", path=path)

    def test_remote_origin_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connection-v1.json"
            with self.assertRaises(LocalCredentialError):
                publish_tokens("https://example.com", "x" * 40, "y" * 40, path=path)
            self.assertFalse(path.exists())

    def test_rotated_pairing_is_persisted_and_failed_persistence_keeps_old_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "connection-v1.json"
            token, pairing = "x" * 40, "y" * 40
            bridge = BrowserBridgeService(pairing_token=pairing, pairing_token_source="windows_user_store")
            bridge.set_pairing_persistence(lambda replacement: publish_tokens("http://127.0.0.1:7860", token, replacement, path=path))
            rotated = asyncio.run(bridge.rotate_pairing_token())
            self.assertEqual(load_tokens("http://127.0.0.1:7860", path=path)["browser_pairing"], rotated)
            self.assertTrue(bridge.pairing_info("")["persistent_across_restarts"])
            bridge.set_pairing_persistence(lambda replacement: False)
            with self.assertRaises(BrowserBridgeError):
                asyncio.run(bridge.revoke_pairing())
            self.assertEqual(bridge.pairing_info("")["pairing_token"], rotated)
