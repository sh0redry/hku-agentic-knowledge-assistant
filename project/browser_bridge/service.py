from __future__ import annotations

import asyncio
import hmac
import re
import secrets
import threading
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from browser_bridge.models import (
    BrowserTabState,
    ExtensionResultMessage,
    HeartbeatMessage,
    PairMessage,
)
from connectors.sis.protocol import BrowserCommand, BrowserCommandResult


EXTENSION_ORIGIN_PATTERN = re.compile(r"^chrome-extension://([a-p]{32})$")
MAX_MESSAGE_CHARACTERS = 256_000


class BrowserBridgeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BrowserBridgeService:
    """In-memory, localhost-only command bridge for one paired extension."""

    def __init__(
        self,
        *,
        allowed_extension_ids: set[str] | None = None,
        heartbeat_timeout: float = 45.0,
        command_timeout: float = 10.0,
    ):
        self._allowed_extension_ids = allowed_extension_ids or set()
        self._heartbeat_timeout = heartbeat_timeout
        self._command_timeout = command_timeout
        self._pairing_token = secrets.token_urlsafe(32)
        self._paired_extension_id: str | None = None
        self._extension_version: str | None = None
        self._websocket: WebSocket | None = None
        self._websocket_loop: asyncio.AbstractEventLoop | None = None
        self._last_heartbeat = 0.0
        self._tab_state = BrowserTabState()
        self._pending: dict[str, asyncio.Future] = {}
        self._last_command: str | None = None
        self._last_command_stage: str | None = None
        self._last_command_error: str | None = None
        self._state_lock = threading.RLock()

    def pairing_info(self, websocket_url: str) -> dict[str, Any]:
        with self._state_lock:
            return {
                "pairing_token": self._pairing_token,
                "websocket_url": websocket_url,
                "paired_extension_id": self._paired_extension_id,
                "security": "localhost + token + extension-origin pinning",
            }

    def rotate_pairing_token(self) -> str:
        with self._state_lock:
            self._pairing_token = secrets.token_urlsafe(32)
            return self._pairing_token

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            age = time.monotonic() - self._last_heartbeat if self._last_heartbeat else None
            socket_connected = self._websocket is not None
            fresh = socket_connected and age is not None and age <= self._heartbeat_timeout
            status = "connected" if fresh else ("stale" if socket_connected else "disconnected")
            return {
                "id": "sis_browser",
                "status": status,
                "mode": "local_browser_read_only",
                "safe_for_writes": False,
                "paired_extension_id": self._paired_extension_id,
                "extension_version": self._extension_version,
                "last_heartbeat_seconds": round(age, 1) if age is not None else None,
                "tab": self._tab_state.model_dump(mode="json"),
                "last_command": {
                    "name": self._last_command,
                    "stage": self._last_command_stage,
                    "error": self._last_command_error,
                },
                "message": self._status_message(status),
            }

    @staticmethod
    def _status_message(status: str) -> str:
        if status == "connected":
            return "Read-only extension connected. No SIS write commands are available."
        if status == "stale":
            return "Extension heartbeat is stale; reopen its popup or reload the extension."
        return "Install and pair the local read-only Chrome extension."

    def _extension_id_from_origin(self, origin: str | None) -> str | None:
        match = EXTENSION_ORIGIN_PATTERN.fullmatch(origin or "")
        return match.group(1) if match else None

    def _is_extension_allowed(self, extension_id: str) -> bool:
        if self._allowed_extension_ids:
            return extension_id in self._allowed_extension_ids
        return self._paired_extension_id in {None, extension_id}

    async def handle_websocket(self, websocket: WebSocket) -> None:
        extension_id = self._extension_id_from_origin(websocket.headers.get("origin"))
        if not extension_id or not self._is_extension_allowed(extension_id):
            await websocket.close(code=4403, reason="Extension origin is not allowed.")
            return

        await websocket.accept()
        try:
            raw_pair = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
            pair = PairMessage.model_validate(raw_pair)
            with self._state_lock:
                expected_token = self._pairing_token
            if not hmac.compare_digest(pair.token, expected_token):
                await websocket.close(code=4401, reason="Invalid pairing token.")
                return

            if not await self._activate_connection(
                websocket, extension_id, pair.extension_version
            ):
                await websocket.close(code=4403, reason="A different extension is already paired.")
                return
            await websocket.send_json(
                {
                    "type": "paired",
                    "protocol_version": 1,
                    "extension_id": extension_id,
                    "read_only": True,
                }
            )

            while True:
                payload = await websocket.receive_json()
                if len(str(payload)) > MAX_MESSAGE_CHARACTERS:
                    await websocket.close(code=4409, reason="Bridge message is too large.")
                    return
                await self._handle_message(payload)
        except (WebSocketDisconnect, asyncio.TimeoutError):
            pass
        except ValidationError as exc:
            await websocket.send_json(
                {"type": "error", "code": "INVALID_MESSAGE", "message": str(exc)}
            )
            await websocket.close(code=4400, reason="Invalid bridge message.")
        finally:
            self._deactivate_connection(websocket)

    async def _activate_connection(
        self, websocket: WebSocket, extension_id: str, extension_version: str
    ) -> bool:
        previous = None
        with self._state_lock:
            if not self._is_extension_allowed(extension_id):
                return False
            previous = self._websocket
            self._paired_extension_id = extension_id
            self._extension_version = extension_version
            self._websocket = websocket
            self._websocket_loop = asyncio.get_running_loop()
            self._last_heartbeat = time.monotonic()
            self._tab_state = BrowserTabState()
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4002, reason="Replaced by a new paired connection.")
            except RuntimeError:
                pass
        return True

    async def _handle_message(self, payload: dict) -> None:
        message_type = payload.get("type")
        if message_type == "heartbeat":
            heartbeat = HeartbeatMessage.model_validate(payload)
            with self._state_lock:
                self._last_heartbeat = time.monotonic()
                if heartbeat.tab is not None:
                    self._tab_state = heartbeat.tab
            return

        result = ExtensionResultMessage.model_validate(payload)
        with self._state_lock:
            self._last_heartbeat = time.monotonic()
            future = self._pending.pop(result.request_id, None)
        if future is not None and not future.done():
            with self._state_lock:
                self._last_command_stage = "completed"
                self._last_command_error = None if result.ok else str(result.error)
            future.set_result(
                BrowserCommandResult(
                    request_id=result.request_id,
                    ok=result.ok,
                    data=result.data,
                    error=result.error,
                )
            )

    def _deactivate_connection(self, websocket: WebSocket) -> None:
        pending = []
        with self._state_lock:
            if self._websocket is not websocket:
                return
            self._websocket = None
            self._websocket_loop = None
            self._tab_state = BrowserTabState()
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(
                    BrowserBridgeError("BROWSER_DISCONNECTED", "Browser extension disconnected.")
                )

    async def request(self, command: BrowserCommand) -> BrowserCommandResult:
        with self._state_lock:
            websocket = self._websocket
            websocket_loop = self._websocket_loop
            status = self.status()["status"]
        if (
            websocket is None
            or websocket_loop is None
            or not websocket_loop.is_running()
            or status != "connected"
        ):
            raise BrowserBridgeError(
                "BROWSER_NOT_CONNECTED", "Pair the read-only browser extension first."
            )

        current_loop = asyncio.get_running_loop()
        if current_loop is websocket_loop:
            return await self._request_on_websocket_loop(command, websocket)

        concurrent_future = asyncio.run_coroutine_threadsafe(
            self._request_on_websocket_loop(command, websocket), websocket_loop
        )
        return await asyncio.wrap_future(concurrent_future)

    async def _request_on_websocket_loop(
        self, command: BrowserCommand, websocket: WebSocket
    ) -> BrowserCommandResult:
        with self._state_lock:
            if websocket is not self._websocket:
                raise BrowserBridgeError(
                    "BROWSER_DISCONNECTED", "Browser extension connection changed."
                )
            self._last_command = command.command.value
            self._last_command_stage = "dispatching"
            self._last_command_error = None

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        with self._state_lock:
            self._pending[command.request_id] = future
        try:
            await websocket.send_json(command.model_dump(mode="json"))
            with self._state_lock:
                self._last_command_stage = "awaiting_extension_result"
            return await asyncio.wait_for(future, timeout=self._command_timeout)
        except asyncio.TimeoutError as exc:
            with self._state_lock:
                self._last_command_stage = "timed_out"
                self._last_command_error = "No result received from the extension."
            raise BrowserBridgeError(
                "BROWSER_TIMEOUT", f"Browser command '{command.command.value}' timed out."
            ) from exc
        finally:
            with self._state_lock:
                self._pending.pop(command.request_id, None)
