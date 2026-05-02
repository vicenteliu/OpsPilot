"""OpsPilot exception hierarchy."""

from __future__ import annotations


class OpsPilotError(Exception):
    """Base for all OpsPilot exceptions."""


class ConfigError(OpsPilotError):
    """Configuration loading / validation error."""


class SchemaError(OpsPilotError):
    """JSON schema validation or registry error."""

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        schema_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.schema_name = schema_name


class RedactionError(OpsPilotError):
    """PII / redaction violation. Stage 2+ uses this; declared early for stable imports."""


class ProviderError(OpsPilotError):
    """LLM provider call failure. Stage 1 PR-3 uses this; declared early for stable imports."""

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
