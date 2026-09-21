from __future__ import annotations

from typing import Any

import httpx


class APIClientError(RuntimeError):
    pass


class HKUAgentsAPIClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 310,
        integration_token: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.integration_token = integration_token

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            try:
                detail: Any = exc.response.json()
            except ValueError:
                detail = exc.response.text
            raise APIClientError(f"API returned {exc.response.status_code}: {detail}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise APIClientError(f"Cannot reach the local HKU AGENTS API: {exc}") from exc

    def health(self) -> dict:
        return self._request("GET", "/api/v1/health")

    def capabilities(self) -> dict:
        return self._request("GET", "/api/v1/capabilities")

    def connections(self) -> dict:
        return self._request("GET", "/api/v1/connections")

    def browser_pairing(self) -> dict:
        return self._request("GET", "/api/v1/browser/pairing")

    def rotate_browser_pairing(self) -> dict:
        return self._request("POST", "/api/v1/browser/pairing/rotate")

    def revoke_browser_pairing(self) -> dict:
        return self._request("POST", "/api/v1/browser/pairing/revoke")

    def browser_status(self) -> dict:
        return self._request("GET", "/api/v1/browser/status")

    def browser_targets(self) -> dict:
        return self._request("GET", "/api/v1/browser/targets")

    def bind_sis_tab(self) -> dict:
        return self._request("POST", "/api/v1/browser/sis/bind")

    def bind_hku_tab(self) -> dict:
        return self._request("POST", "/api/v1/browser/hku/bind")

    def open_enrollment_add_classes(self, term_label: str | None = None) -> dict:
        payload = {} if term_label is None else {"term_label": term_label}
        return self._integration_request("POST", "/sis/navigate", json=payload)

    def inspect_sis_page(self) -> dict:
        return self._request("GET", "/api/v1/browser/sis/page")

    def inspect_sis_cart(self) -> dict:
        return self._request("GET", "/api/v1/browser/sis/cart")

    def tasks(self) -> dict:
        return self._request("GET", "/api/v1/tasks")

    def chat(self, message: str, history: list, session_id: str) -> dict:
        normalized_history = [item for item in history if isinstance(item, dict)]
        return self._request(
            "POST",
            "/api/v1/chat",
            json={"message": message, "history": normalized_history, "session_id": session_id},
        )

    def sis_preflight(self, payload: dict) -> dict:
        return self._request("POST", "/api/v1/sis/preflight", json=payload)

    def sis_live_preflight(self, payload: dict) -> dict:
        return self._request("POST", "/api/v1/browser/sis/preflight", json=payload)

    def _integration_request(self, method: str, path: str, **kwargs) -> dict:
        if not self.integration_token:
            raise APIClientError("The local Integration API token is not configured.")
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self.integration_token}"
        return self._request(method, f"/api/v1/integration{path}", headers=headers, **kwargs)

    def integration_status(self) -> dict:
        return self._integration_request("GET", "/status")

    def integration_sis_sync(self) -> dict:
        return self._integration_request("POST", "/sis/sync")

    def integration_sis_preflight(self, payload: dict) -> dict:
        return self._integration_request("POST", "/sis/preflight", json=payload)

    def integration_sis_navigate_and_preflight(self, payload: dict) -> dict:
        return self._integration_request(
            "POST", "/sis/navigate-and-preflight", json=payload
        )

    def timetable_sync_weekly(self, term_label: str) -> dict:
        return self._integration_request(
            "POST", "/sis/timetable/sync-weekly", json={"term_label": term_label}
        )

    def timetable_next_class(self, payload: dict) -> dict:
        return self._integration_request("POST", "/sis/timetable/next-class", json=payload)

    def timetable_free_slots(self, payload: dict) -> dict:
        return self._integration_request("POST", "/sis/timetable/free-slots", json=payload)

    def timetable_check_conflicts(self, payload: dict) -> dict:
        return self._integration_request(
            "POST", "/sis/timetable/check-conflicts", json=payload
        )

    def timetable_exam_status(self, payload: dict) -> dict:
        return self._integration_request("POST", "/sis/timetable/exam-status", json=payload)

    def moodle_inspect_dashboard(self) -> dict:
        return self._integration_request("POST", "/moodle/dashboard/inspect", json={})

    def moodle_list_courses(self) -> dict:
        return self._integration_request("POST", "/moodle/courses/list", json={})

    def moodle_upcoming_assignments(self, days_ahead: int) -> dict:
        return self._integration_request(
            "POST",
            "/moodle/assignments/upcoming",
            json={"days_ahead": int(days_ahead)},
        )

    def portal_notices(self) -> dict:
        return self._integration_request("POST", "/portal/notices/list", json={})

    def library_research_search(self, query: str, field: str, scope: str, limit: int) -> dict:
        return self._integration_request(
            "POST",
            "/library/research/search",
            json={"query": query, "field": field, "scope": scope, "limit": int(limit)},
        )

    def library_research_item(self, record_id: str) -> dict:
        return self._integration_request(
            "POST", "/library/research/item", json={"record_id": record_id}
        )

    def library_research_access_options(self, record_id: str) -> dict:
        return self._integration_request(
            "POST", "/library/research/access-options", json={"record_id": record_id}
        )

    def library_space_availability(self, facility_type: str) -> dict:
        return self._integration_request(
            "POST",
            "/library/spaces/search-availability",
            json={"facility_type": facility_type},
        )

    def library_list_facilities(self) -> dict:
        return self._integration_request(
            "POST", "/library/spaces/list-facilities", json={}
        )

    def library_hours_and_locations(self) -> dict:
        return self._integration_request(
            "POST", "/library/hours-and-locations", json={}
        )

    def daily_briefing(
        self,
        term_label: str,
        days_ahead: int,
        max_cache_age_minutes: int,
    ) -> dict:
        payload = {
            "days_ahead": int(days_ahead),
            "max_cache_age_minutes": int(max_cache_age_minutes),
        }
        if term_label.strip():
            payload["term_label"] = term_label.strip()
        return self._integration_request("POST", "/briefing/today", json=payload)
