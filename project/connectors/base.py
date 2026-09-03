from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    id: str

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError
