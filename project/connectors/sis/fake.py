from __future__ import annotations

from connectors.base import BaseConnector
from connectors.sis.models import SISPreflightRequest


class FakeSISConnector(BaseConnector):
    """A zero-network simulator used until the browser runtime is implemented."""

    id = "sis_simulator"

    def health(self) -> dict:
        return {
            "id": self.id,
            "status": "connected",
            "mode": "simulated",
            "safe_for_writes": False,
            "message": "Synthetic SIS connector; no browser or HKU system is contacted.",
        }

    def preflight(self, request: SISPreflightRequest) -> dict:
        issues: list[str] = []
        warnings = ["SIMULATED RESULT: no browser or HKU SIS connection was used."]
        if request.origin != "https://sis-main.hku.hk":
            issues.append("Origin must be exactly https://sis-main.hku.hk.")
        if not request.logged_in:
            issues.append("SIS session is not logged in.")
        if request.page_kind not in {"cart", "blocked"}:
            issues.append("Open the Temporary Course List before preflight.")
        if request.term_label != request.current_term_label:
            issues.append("Current SIS term does not match the requested term.")

        expected = {item.comparison_key(): item for item in request.expected_courses}
        visible = {item.comparison_key(): item for item in request.visible_courses}
        missing = [expected[key].model_dump() for key in sorted(expected.keys() - visible.keys())]
        unexpected = [visible[key].model_dump() for key in sorted(visible.keys() - expected.keys())]
        if missing:
            issues.append("Expected course/section/class entries are missing from the cart.")
        if unexpected:
            issues.append("The cart contains unapproved course/section/class entries.")

        return {
            "ok": not issues,
            "simulated": True,
            "no_requests_sent": True,
            "page_kind": request.page_kind,
            "term_label": request.current_term_label,
            "expected_courses": [item.model_dump() for item in request.expected_courses],
            "visible_courses": [item.model_dump() for item in request.visible_courses],
            "missing": missing,
            "unexpected": unexpected,
            "issues": issues,
            "warnings": warnings,
        }
