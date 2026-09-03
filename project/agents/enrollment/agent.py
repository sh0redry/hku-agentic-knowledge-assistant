from agents.base import BaseCapability
from agents.models import (
    CapabilityManifest,
    CapabilityMode,
    ConfirmationMode,
    ExecutionContext,
    RiskLevel,
)
from connectors.sis.fake import FakeSISConnector
from connectors.sis.models import SISPreflightRequest


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
