from agents.base import BaseCapability
from agents.errors import CapabilityError
from agents.models import (
    CapabilityManifest,
    CapabilityMode,
    ConfirmationMode,
    ExecutionContext,
    RiskLevel,
)
from browser_bridge.service import BrowserBridgeError
from connectors.sis.browser import BrowserSISConnector
from connectors.sis.fake import FakeSISConnector
from connectors.sis.models import (
    CourseSelection,
    SISLivePreflightRequest,
    SISNavigationRequest,
    SISPreflightRequest,
)
from connectors.sis.validation import evaluate_preflight


def _evaluate_live_snapshot(
    request: SISLivePreflightRequest,
    snapshot: dict,
) -> dict:
    visible_courses = [
        CourseSelection.model_validate(course)
        for course in snapshot["temporary_courses"]
    ]
    return evaluate_preflight(
        requested_term_label=request.term_label,
        expected_courses=request.expected_courses,
        origin=snapshot.get("origin"),
        logged_in=snapshot.get("logged_in"),
        page_kind=snapshot.get("page_kind", "unknown"),
        current_term_label=snapshot.get("term_label"),
        visible_courses=visible_courses,
        simulated=False,
        match_class_number=False,
    )


class SISPreflightCapability(BaseCapability):
    input_model = SISPreflightRequest
    manifest = CapabilityManifest(
        id="sis.enrollment.preflight",
        agent="enrollment",
        title="SIS Enrollment Preflight (Simulator)",
        description="Validate term and exact course/section/class-number sets without contacting SIS.",
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_simulator"],
        availability="simulated",
        input_schema="SISPreflightRequest",
        output_schema="SISPreflightResult",
        timeout_seconds=10,
    )

    def __init__(self, connector: FakeSISConnector):
        self.connector = connector

    async def execute(self, validated_input: SISPreflightRequest, context: ExecutionContext) -> dict:
        return self.connector.preflight(validated_input)


class SISLivePreflightCapability(BaseCapability):
    input_model = SISLivePreflightRequest
    manifest = CapabilityManifest(
        id="sis.enrollment.live_preflight",
        agent="enrollment",
        title="SIS Enrollment Live Preflight",
        description="Read the open SIS Temporary Course List and compare it with exact expected entries.",
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_read_only",
        input_schema="SISLivePreflightRequest",
        output_schema="SISPreflightResult",
        timeout_seconds=15,
    )

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

    async def execute(
        self, validated_input: SISLivePreflightRequest, context: ExecutionContext
    ) -> dict:
        try:
            snapshot = await self.connector.preflight_snapshot()
        except BrowserBridgeError as exc:
            raise CapabilityError(exc.code, str(exc)) from exc

        return _evaluate_live_snapshot(validated_input, snapshot)


class SISNavigateAndPreflightCapability(BaseCapability):
    """Compose restricted navigation and strict cart comparison into one read-only task."""

    input_model = SISLivePreflightRequest
    manifest = CapabilityManifest(
        id="sis.enrollment.navigate_and_preflight",
        agent="enrollment",
        title="Navigate to SIS and Run Enrollment Preflight",
        description=(
            "From an authenticated HKU Portal tab, follow the fixed SIS navigation path, "
            "select the exact requested term, read the Temporary Course List, and compare "
            "it with the expected course/section set without changing enrollment data."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_restricted_navigation_read_only",
        input_schema="SISLivePreflightRequest",
        output_schema="SISNavigateAndPreflightResult",
        timeout_seconds=42,
    )

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

    async def execute(
        self, validated_input: SISLivePreflightRequest, context: ExecutionContext
    ) -> dict:
        try:
            binding = await self.connector.bind_hku_tab()
            navigation = await self.connector.open_enrollment_add_classes(
                validated_input.term_label
            )
        except BrowserBridgeError as exc:
            raise CapabilityError(exc.code, str(exc)) from exc

        snapshot = navigation["snapshot"]
        preflight = _evaluate_live_snapshot(validated_input, snapshot)
        navigation_steps = navigation.get("steps", [])
        navigation_interactions_performed = any(
            step != "target_already_open" for step in navigation_steps
        )
        term_selection_performed = "sis_select_term" in navigation_steps
        navigation_summary = {
            key: value for key, value in navigation.items() if key != "snapshot"
        }
        return {
            "ok": preflight["ok"],
            "ready": preflight["ready"],
            "read_only": True,
            "simulated": False,
            "sis_write_requests_sent": 0,
            "navigation_interactions_performed": navigation_interactions_performed,
            "term_selection_performed": term_selection_performed,
            "enrollment_writes_performed": 0,
            "binding": {
                "origin": binding.get("origin"),
                "page_kind": binding.get("page_kind"),
                "logged_in": binding.get("logged_in"),
            },
            "navigation": navigation_summary,
            "course_lists": snapshot,
            "preflight": preflight,
        }


class SISOpenEnrollmentAddClassesCapability(BaseCapability):
    input_model = SISNavigationRequest
    manifest = CapabilityManifest(
        id="sis.navigation.open_enrollment_add_classes",
        agent="enrollment",
        title="Open SIS Enrollment Add Classes",
        description=(
            "Navigate from an authenticated HKU Portal or SIS tab to Enrollment Add "
            "Classes through fixed browser-side targets, selecting only the exact "
            "validated term when SIS requests it, without changing enrollment data."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_restricted_navigation",
        input_schema="SISNavigationRequest",
        output_schema="SISNavigationResult",
        timeout_seconds=38,
    )

    def __init__(self, connector: BrowserSISConnector):
        self.connector = connector

    async def execute(self, validated_input: SISNavigationRequest, context: ExecutionContext) -> dict:
        try:
            return await self.connector.open_enrollment_add_classes(
                validated_input.term_label
            )
        except BrowserBridgeError as exc:
            raise CapabilityError(exc.code, str(exc)) from exc
