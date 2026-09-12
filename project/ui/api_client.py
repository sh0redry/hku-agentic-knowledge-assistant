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
