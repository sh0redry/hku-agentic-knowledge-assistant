from __future__ import annotations

from browser_bridge.models import SISPageSnapshot
from browser_bridge.service import BrowserBridgeError, BrowserBridgeService
from connectors.base import BaseConnector
from connectors.sis.protocol import BrowserCommand, BrowserCommandName


class BrowserSISConnector(BaseConnector):
    """Deterministic read-only adapter for the paired local extension."""

    id = "sis_browser"

    def __init__(self, bridge: BrowserBridgeService):
        self.bridge = bridge

    def health(self) -> dict:
        return self.bridge.status()

    async def bind_tab(self) -> dict:
        data = await self._command(BrowserCommandName.BIND_SIS_TAB)
        return SISPageSnapshot.model_validate(data).model_dump(mode="json")

    async def inspect_page(self) -> dict:
        data = await self._command(BrowserCommandName.INSPECT_PAGE)
        return SISPageSnapshot.model_validate(data).model_dump(mode="json")

    async def inspect_cart(self) -> dict:
        data = await self._command(BrowserCommandName.INSPECT_CART)
        return self._validate_cart(data)

    async def preflight_snapshot(self) -> dict:
        data = await self._command(BrowserCommandName.PREFLIGHT)
        return self._validate_cart(data)

    @staticmethod
    def _validate_cart(data: dict) -> dict:
        snapshot = SISPageSnapshot.model_validate(data)
        if snapshot.page_kind != "cart":
            raise BrowserBridgeError(
                "WRONG_SIS_PAGE", "Open the Temporary Course List before inspecting the cart."
            )
        return snapshot.model_dump(mode="json")

    async def _command(self, name: BrowserCommandName) -> dict:
        result = await self.bridge.request(BrowserCommand(command=name))
        if not result.ok:
            error = result.error or {}
            raise BrowserBridgeError(
                str(error.get("code", "BROWSER_COMMAND_FAILED")),
                str(error.get("message", f"Browser command '{name.value}' failed.")),
            )
        return result.data
