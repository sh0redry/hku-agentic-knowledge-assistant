from __future__ import annotations

from .base import BaseCapability
from .errors import CapabilityNotFoundError


class CapabilityRegistry:
    def __init__(self):
        self._capabilities: dict[str, BaseCapability] = {}

    def register(self, capability: BaseCapability) -> None:
        capability_id = capability.manifest.id
        if capability_id in self._capabilities:
            raise ValueError(f"Capability '{capability_id}' is already registered.")
        self._capabilities[capability_id] = capability

    def get(self, capability_id: str) -> BaseCapability:
        try:
            return self._capabilities[capability_id]
        except KeyError as exc:
            raise CapabilityNotFoundError(capability_id) from exc

    def manifests(self):
        return [item.manifest for item in sorted(self._capabilities.values(), key=lambda item: item.manifest.id)]
