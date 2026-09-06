from __future__ import annotations

from connectors.base import BaseConnector
from connectors.sis.models import SISPreflightRequest
from connectors.sis.validation import evaluate_preflight


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
        result = evaluate_preflight(
            requested_term_label=request.term_label,
            expected_courses=request.expected_courses,
            origin=request.origin,
            logged_in=request.logged_in,
            page_kind=request.page_kind,
            current_term_label=request.current_term_label,
            visible_courses=request.visible_courses,
            simulated=True,
        )
        result["no_requests_sent"] = True
        return result
