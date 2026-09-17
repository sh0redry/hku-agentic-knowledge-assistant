from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from agents.base import BaseCapability
from agents.models import (
    CapabilityManifest,
    CapabilityMode,
    ConfirmationMode,
    ExecutionContext,
    RiskLevel,
)
from services.briefing import DailyBriefingService


class DailyBriefingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term_label: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}\s+Sem\s+[12]$"
    )
    as_of: datetime | None = None
    days_ahead: int = Field(default=7, ge=1, le=14)
    max_cache_age_minutes: int = Field(default=120, ge=1, le=10080)


class DailyBriefingCapability(BaseCapability):
    input_model = DailyBriefingRequest
    manifest = CapabilityManifest(
        id="briefing.today",
        version=1,
        agent="briefing",
        title="HKU Daily Briefing",
        description=(
            "Combine the process-local SIS timetable and Moodle deadline caches. "
            "This capability performs no browser interaction and reports missing, "
            "stale, mismatched, or insufficiently covered sources explicitly."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.LOW,
        confirmation=ConfirmationMode.NONE,
        required_connections=[],
        availability="process_cache_derived",
        input_schema="DailyBriefingRequest",
        output_schema="DailyBriefingResult",
        timeout_seconds=5,
    )

    def __init__(self, briefing: DailyBriefingService) -> None:
        self.briefing = briefing

    def persisted_result(self, result: dict) -> dict:
        return {
            "read_only": True,
            "derived_locally": True,
            "browser_interactions_performed": False,
            "domain_writes_performed": 0,
            "as_of": result.get("as_of"),
            "complete": result.get("complete", False),
            "source_status": result.get("source_status", {}),
            "counts": result.get("counts", {}),
            "private_briefing_details_persisted": False,
        }

    async def execute(
        self, validated_input: DailyBriefingRequest, context: ExecutionContext
    ) -> dict:
        return self.briefing.build(
            term_label=validated_input.term_label,
            as_of=validated_input.as_of,
            days_ahead=validated_input.days_ahead,
            max_cache_age_minutes=validated_input.max_cache_age_minutes,
        )
