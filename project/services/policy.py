from agents.errors import PolicyDeniedError
from agents.models import CapabilityManifest, CapabilityMode, ConfirmationMode, RiskLevel


class PolicyEngine:
    """Central safety policy independent of LLM behavior."""

    @staticmethod
    def confirmation_required(manifest: CapabilityManifest) -> bool:
        return (
            manifest.mode == CapabilityMode.WRITE
            or manifest.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            or manifest.confirmation != ConfirmationMode.NONE
        )

    def assert_executable(self, manifest: CapabilityManifest, confirmed: bool) -> None:
        if self.confirmation_required(manifest) and not confirmed:
            raise PolicyDeniedError(
                "CONFIRMATION_REQUIRED",
                f"Capability '{manifest.id}' requires explicit confirmation.",
                {"capability": manifest.id, "risk": manifest.risk.value},
            )
