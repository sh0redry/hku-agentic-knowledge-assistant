from __future__ import annotations

import threading
import time
from typing import Iterable

from browser_bridge.models import BrowserTabState, BrowserTargetState


TARGET_SYSTEMS = ("portal", "sis", "moodle", "library")

RECOVERY = {
    "portal": "Open HKU Portal and complete login/MFA manually.",
    "sis": "Use a verified Portal-to-SIS navigation command after Portal login.",
    "moodle": "Open Moodle through HKU Portal and use the HKU Portal User login when required.",
    "library": "Open My Library through HKU Portal and complete any visible authentication step.",
}


class BrowserSessionRegistry:
    """Tracks sanitized, per-system browser targets while preserving a legacy primary tab."""

    def __init__(self) -> None:
        self._targets: dict[str, BrowserTargetState] = {}
        self._seen_at: dict[str, float] = {}
        self._lock = threading.RLock()

    def clear(self) -> None:
        with self._lock:
            self._targets.clear()
            self._seen_at.clear()

    def update(
        self,
        targets: Iterable[BrowserTargetState],
        legacy_tab: BrowserTabState | None = None,
    ) -> None:
        now = time.monotonic()
        incoming = {target.system: target for target in targets}
        if legacy_tab is not None and legacy_tab.bound and legacy_tab.origin:
            system = (
                "portal"
                if legacy_tab.origin in {
                    "https://hkuportal.hku.hk",
                    "https://studentportal.hku.hk",
                }
                else "sis"
                if legacy_tab.origin == "https://sis-main.hku.hk"
                else None
            )
            if system and system not in incoming:
                incoming[system] = BrowserTargetState(
                    system=system,
                    origin=legacy_tab.origin,
                    path="/",
                    logged_in=legacy_tab.logged_in,
                    page_kind=legacy_tab.page_kind,
                    active=True,
                    parser_version=None,
                )
        with self._lock:
            self._targets = incoming
            self._seen_at = {system: now for system in incoming}

    def snapshot(self, *, bridge_connected: bool, heartbeat_timeout: float) -> list[dict]:
        now = time.monotonic()
        result = []
        with self._lock:
            for system in TARGET_SYSTEMS:
                target = self._targets.get(system)
                seen_at = self._seen_at.get(system)
                age = now - seen_at if seen_at is not None else None
                fresh = bool(
                    target is not None
                    and bridge_connected
                    and age is not None
                    and age <= heartbeat_timeout
                )
                if target is None:
                    connection_state = "not_detected"
                elif not fresh:
                    connection_state = "stale"
                elif target.logged_in is True:
                    connection_state = "authenticated"
                elif target.logged_in is False:
                    connection_state = "authentication_required"
                else:
                    connection_state = "detected"
                payload = {
                    "system": system,
                    "detected": target is not None,
                    "connection_state": connection_state,
                    "fresh": fresh,
                    "origin": target.origin if target else None,
                    "path": target.path if target else None,
                    "logged_in": target.logged_in if target else None,
                    "page_kind": target.page_kind if target else "unknown",
                    "parser_version": target.parser_version if target else None,
                    "active": target.active if target else False,
                    "last_seen_seconds": round(age, 1) if age is not None else None,
                    "safe_for_writes": False,
                    "recovery": RECOVERY[system],
                }
                result.append(payload)
        return result
