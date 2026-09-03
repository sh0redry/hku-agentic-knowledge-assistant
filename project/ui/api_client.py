from __future__ import annotations

from typing import Any

import httpx


class APIClientError(RuntimeError):
    pass


class HKUAgentsAPIClient:
    def __init__(self, base_url: str, timeout: float = 310):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

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
