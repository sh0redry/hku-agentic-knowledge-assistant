from __future__ import annotations

from pydantic import BaseModel, ConfigDict

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
from services.portal import PortalNoticeService


class PortalNoticeListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _supported_parser(value: object, minimum: tuple[int, int, int]) -> bool:
    try:
        return tuple(int(part) for part in str(value).split(".")) >= minimum
    except (TypeError, ValueError):
        return False


class PortalNoticeListCapability(BaseCapability):
    input_model = PortalNoticeListRequest
    manifest = CapabilityManifest(
        id="portal.notices.list",
        version=1,
        agent="portal",
        title="List visible HKU Portal notices",
        description=(
            "Read News notices currently exposed by the authenticated HKU Portal home "
            "page and cache them in process memory. It does not open notice detail pages."
        ),
        mode=CapabilityMode.READ,
        risk=RiskLevel.MEDIUM,
        confirmation=ConfirmationMode.NONE,
        required_connections=["sis_browser"],
        availability="local_browser_read_only_private_memory",
        input_schema="PortalNoticeListRequest",
        output_schema="PortalNoticeListResult",
        timeout_seconds=15,
    )

    def __init__(self, connector: BrowserSISConnector, notices: PortalNoticeService):
        self.connector = connector
        self.notices = notices

    def persisted_result(self, result: dict) -> dict:
        notice_list = result.get("notice_list") or {}
        return {
            "read_only": True,
            "domain_writes_performed": 0,
            "portal_writes_performed": 0,
            "notice_count": notice_list.get("notice_count", 0),
            "source_fetched_at": notice_list.get("fetched_at"),
            "private_notice_details_persisted": False,
        }

    async def execute(
        self, validated_input: PortalNoticeListRequest, context: ExecutionContext
    ) -> dict:
        try:
            snapshot = await self.connector.list_portal_notices()
        except BrowserBridgeError as exc:
            if exc.code in {"COMMAND_NOT_ALLOWED", "PAGE_SCRIPT_UNAVAILABLE"}:
                raise CapabilityError(
                    "EXTENSION_UPDATE_REQUIRED",
                    "Reload HKU AGENTS Browser Bridge 0.17.5 and refresh HKU Portal.",
                ) from exc
            raise CapabilityError(exc.code, str(exc)) from exc

        diagnostics = snapshot.get("diagnostics") or {}
        if not _supported_parser(diagnostics.get("parser_version"), (0, 1, 3)):
            raise CapabilityError(
                "EXTENSION_UPDATE_REQUIRED",
                "Reload HKU AGENTS Browser Bridge 0.17.5 before reading Portal notices.",
            )
        if int(diagnostics.get("unparsed_notice_candidate_count", 0)):
            raise CapabilityError(
                "PORTAL_NOTICE_PARSE_INCOMPLETE",
                "One or more visible Portal notice candidates could not be parsed safely.",
                {"diagnostics": diagnostics},
            )

        notice_list = self.notices.update(
            snapshot.get("notices", []),
            {
                "kind": "portal_home_visible_news",
                "origin": snapshot.get("origin"),
                "page_kind": snapshot.get("page_kind"),
                "parser_version": diagnostics.get("parser_version"),
                "visibility_scope": "portal_home_dom",
            },
        )
        warnings = []
        if not diagnostics.get("news_marker_found"):
            warnings.append(
                "The Portal News marker was not visible; an empty result does not prove "
                "that there are no notices."
            )
        elif int(diagnostics.get("notice_candidate_count", 0)) == 0:
            warnings.append(
                "No notice candidates were exposed in the current Portal DOM; an empty "
                "result does not prove that there are no notices."
            )
        return {
            "read_only": True,
            "systems_contacted": ["portal"],
            "navigation_interactions_performed": False,
            "data_reads_performed": 1,
            "domain_writes_performed": 0,
            "portal_writes_performed": 0,
            "notice_detail_pages_opened": 0,
            "binding": {
                "origin": snapshot.get("origin"),
                "page_kind": snapshot.get("page_kind"),
                "logged_in": snapshot.get("logged_in"),
            },
            "notice_list": notice_list,
            "diagnostics": diagnostics,
            "warnings": warnings,
        }
