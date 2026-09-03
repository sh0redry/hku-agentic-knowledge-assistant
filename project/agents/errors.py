class CapabilityError(Exception):
    """Base error with a stable, API-safe error code."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class CapabilityNotFoundError(CapabilityError):
    def __init__(self, capability_id: str):
        super().__init__(
            "CAPABILITY_NOT_FOUND",
            f"Capability '{capability_id}' is not registered.",
            {"capability": capability_id},
        )


class PolicyDeniedError(CapabilityError):
    pass


class ExecutionUnknownError(CapabilityError):
    """The external system may have accepted a request, but the result is unknown."""
