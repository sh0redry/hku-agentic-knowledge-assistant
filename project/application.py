from __future__ import annotations

from pathlib import Path

import config
from browser_bridge.service import BrowserBridgeService
from agents.enrollment.agent import (
    SISLivePreflightCapability,
    SISNavigateAndPreflightCapability,
    SISOpenEnrollmentAddClassesCapability,
    SISPreflightCapability,
)
from agents.knowledge.agent import KnowledgeAnswerCapability
from agents.briefing.agent import DailyBriefingCapability
from agents.moodle.agent import (
    MoodleCourseListCapability,
    MoodleDashboardInspectCapability,
    MoodleUpcomingAssignmentsCapability,
)
from agents.portal.agent import PortalNoticeListCapability
from agents.library.agent import (
    LibraryFacilityListCapability,
    LibraryHoursAndLocationsCapability,
    LibraryResearchAccessOptionsCapability,
    LibraryResearchItemCapability,
    LibraryResearchSearchCapability,
    LibrarySpaceAvailabilityCapability,
    LibrarySpaceBookCapability,
    LibrarySpaceBookingPreviewCapability,
)
from agents.timetable.agent import (
    SISExamStatusCapability,
    SISFreeSlotsCapability,
    SISNextClassCapability,
    SISTimetableConflictCapability,
    SISTimetableSyncCapability,
)
from agents.registry import CapabilityRegistry
from connectors.sis.fake import FakeSISConnector
from connectors.sis.browser import BrowserSISConnector
from services.actions import ActionService
from services.policy import PolicyEngine
from services.store import SQLiteStore
from services.tasks import TaskManager
from services.timetable import TimetableService
from services.moodle import MoodleAssignmentService, MoodleCourseService
from services.briefing import DailyBriefingService
from services.portal import PortalNoticeService
from services.library_booking import LibraryBookingPreviewRegistry


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
            booking_prepare_timeout=config.BROWSER_BOOKING_PREPARE_TIMEOUT_SECONDS,
            booking_submit_timeout=config.BROWSER_BOOKING_SUBMIT_TIMEOUT_SECONDS,
            pairing_token=config.BROWSER_PAIRING_TOKEN,
            pairing_token_source=config.BROWSER_PAIRING_TOKEN_SOURCE,
        )
        self.connectors = {
            "sis_browser": BrowserSISConnector(self.browser_bridge),
            "sis_simulator": FakeSISConnector(),
        }
        self.timetable = TimetableService()
        self.moodle_courses = MoodleCourseService()
        self.moodle_assignments = MoodleAssignmentService()
        self.portal_notices = PortalNoticeService()
        self.library_booking_previews = LibraryBookingPreviewRegistry()
        self.daily_briefing = DailyBriefingService(
            self.timetable, self.moodle_assignments, self.portal_notices
        )

        self.registry.register(KnowledgeAnswerCapability())
        self.registry.register(SISPreflightCapability(self.connectors["sis_simulator"]))
        self.registry.register(SISLivePreflightCapability(self.connectors["sis_browser"]))
        self.registry.register(
            SISNavigateAndPreflightCapability(self.connectors["sis_browser"])
        )
        self.registry.register(
            SISOpenEnrollmentAddClassesCapability(self.connectors["sis_browser"])
        )
        self.registry.register(
            SISTimetableSyncCapability(self.connectors["sis_browser"], self.timetable)
        )
        self.registry.register(SISNextClassCapability(self.timetable))
        self.registry.register(SISFreeSlotsCapability(self.timetable))
        self.registry.register(SISTimetableConflictCapability(self.timetable))
        self.registry.register(SISExamStatusCapability(self.connectors["sis_browser"]))
        self.registry.register(MoodleDashboardInspectCapability(self.connectors["sis_browser"]))
        self.registry.register(
            MoodleCourseListCapability(
                self.connectors["sis_browser"], self.moodle_courses
            )
        )
        self.registry.register(
            MoodleUpcomingAssignmentsCapability(
                self.connectors["sis_browser"], self.moodle_assignments
            )
        )
        self.registry.register(
            PortalNoticeListCapability(
                self.connectors["sis_browser"], self.portal_notices
            )
        )
        self.registry.register(DailyBriefingCapability(self.daily_briefing))
        self.registry.register(LibraryResearchSearchCapability(self.connectors["sis_browser"]))
        self.registry.register(LibraryResearchItemCapability(self.connectors["sis_browser"]))
        self.registry.register(LibraryResearchAccessOptionsCapability(self.connectors["sis_browser"]))
        self.registry.register(LibraryFacilityListCapability())
        self.registry.register(LibraryHoursAndLocationsCapability(self.connectors["sis_browser"]))
        self.registry.register(LibrarySpaceAvailabilityCapability(self.connectors["sis_browser"]))
        self.registry.register(
            LibrarySpaceBookingPreviewCapability(
                self.connectors["sis_browser"], self.library_booking_previews
            )
        )
        self.registry.register(
            LibrarySpaceBookCapability(
                self.connectors["sis_browser"], self.library_booking_previews
            )
        )

        self.tasks = TaskManager(self.registry, self.store)
        self.actions = ActionService(self.registry, self.store, self.tasks, self.policy)

    def connection_status(self) -> list[dict]:
        return [connector.health() for connector in self.connectors.values()]
