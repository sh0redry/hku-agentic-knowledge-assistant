from __future__ import annotations

from pathlib import Path

import config
from browser_bridge.service import BrowserBridgeService
from agents.enrollment.agent import (
    SISLivePreflightCapability,
    SISOpenEnrollmentAddClassesCapability,
    SISPreflightCapability,
)
from agents.knowledge.agent import KnowledgeAnswerCapability
from agents.registry import CapabilityRegistry
from connectors.sis.fake import FakeSISConnector
from connectors.sis.browser import BrowserSISConnector
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
        self.browser_bridge = BrowserBridgeService(
            allowed_extension_ids=config.BROWSER_EXTENSION_IDS,
            heartbeat_timeout=config.BROWSER_HEARTBEAT_TIMEOUT_SECONDS,
            command_timeout=config.BROWSER_COMMAND_TIMEOUT_SECONDS,
        )
        self.connectors = {
            "sis_browser": BrowserSISConnector(self.browser_bridge),
            "sis_simulator": FakeSISConnector(),
        }

        self.registry.register(KnowledgeAnswerCapability())
        self.registry.register(SISPreflightCapability(self.connectors["sis_simulator"]))
        self.registry.register(SISLivePreflightCapability(self.connectors["sis_browser"]))
        self.registry.register(
            SISOpenEnrollmentAddClassesCapability(self.connectors["sis_browser"])
        )

        self.tasks = TaskManager(self.registry, self.store)
        self.actions = ActionService(self.registry, self.store, self.tasks, self.policy)

    def connection_status(self) -> list[dict]:
        return [connector.health() for connector in self.connectors.values()]
