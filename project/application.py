from __future__ import annotations

from pathlib import Path

import config
from agents.enrollment.agent import SISPreflightCapability
from agents.knowledge.agent import KnowledgeAnswerCapability
from agents.registry import CapabilityRegistry
from connectors.sis.fake import FakeSISConnector
from services.actions import ActionService
from services.policy import PolicyEngine
from services.store import SQLiteStore
from services.tasks import TaskManager


class ApplicationContainer:
    """Composition root for the local modular monolith."""

    def __init__(self, db_path: str | Path | None = None):
        self.store = SQLiteStore(db_path or config.APP_DB_PATH)
        self.registry = CapabilityRegistry()
        self.policy = PolicyEngine()
        self.connectors = {"sis_simulator": FakeSISConnector()}

        self.registry.register(KnowledgeAnswerCapability())
        self.registry.register(SISPreflightCapability(self.connectors["sis_simulator"]))

        self.tasks = TaskManager(self.registry, self.store)
        self.actions = ActionService(self.registry, self.store, self.tasks, self.policy)

    def connection_status(self) -> list[dict]:
        return [
            {
                "id": "sis_browser",
                "status": "not_implemented",
                "mode": "local_browser",
                "safe_for_writes": False,
                "message": "Chrome extension and authenticated browser channel are not implemented yet.",
            },
            *(connector.health() for connector in self.connectors.values()),
        ]
