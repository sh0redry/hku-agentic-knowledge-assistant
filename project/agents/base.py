from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from .models import CapabilityManifest, ExecutionContext


class BaseCapability(ABC):
    manifest: CapabilityManifest
    input_model: type[BaseModel]

    def validate_input(self, payload: dict[str, Any]) -> BaseModel:
        return self.input_model.model_validate(payload)

    def preview(self, validated_input: BaseModel) -> dict[str, Any]:
        return {
            "capability": self.manifest.id,
            "mode": self.manifest.mode.value,
            "risk": self.manifest.risk.value,
            "parameters": validated_input.model_dump(mode="json"),
        }

    def persisted_input(self, validated_input: BaseModel) -> dict[str, Any]:
        return validated_input.model_dump(mode="json")

    def persisted_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return result

    @abstractmethod
    async def execute(self, validated_input: BaseModel, context: ExecutionContext) -> dict[str, Any]:
        raise NotImplementedError
