from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class McpAuth(BaseModel):
    type: Literal["none", "api_key_header", "bearer_env", "oauth2"] = "none"
    env: str | None = None
    header: str | None = None


class McpCompliance(BaseModel):
    data_residency: Literal["us", "eu", "apac", "cn", "unspecified"] = "unspecified"
    pii_allowed: bool = False
    telemetry_optout: bool = True


class McpHealthProbe(BaseModel):
    interval_seconds: int = 600
    method: Literal["list_tools", "ping"] = "list_tools"
    failure_threshold: int = 3


class McpLimits(BaseModel):
    rpm: int | None = None
    concurrent: int | None = None
    monthly_budget_usd: float | None = None


class McpServerConfig(BaseModel):
    id: str
    name: str
    description: str = ""
    transport: Literal["stdio", "http", "sse"]
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    tools_prefix: str
    tools_allowlist: list[str] | None = None
    tools_denylist: list[str] | None = None
    enabled: bool = True
    trust: Literal["trusted", "community", "unknown"] = "unknown"
    auth: McpAuth = Field(default_factory=McpAuth)
    compliance: McpCompliance = Field(default_factory=McpCompliance)
    health_probe: McpHealthProbe = Field(default_factory=McpHealthProbe)
    limits: McpLimits = Field(default_factory=McpLimits)


class McpGlobalPolicy(BaseModel):
    default_deny_on_disabled: bool = True
    block_secrets_in_env_literals: bool = True
    audit_every_call: bool = True


class McpConfig(BaseModel):
    version: str
    mcps: list[McpServerConfig]
    global_policy: McpGlobalPolicy = Field(default_factory=McpGlobalPolicy)


class McpToolInfo(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    server_id: str = ""


class McpContent(BaseModel):
    type: Literal["text", "image", "resource"] = "text"
    text: str | None = None
    data: str | None = None
    uri: str | None = None


class McpCallResult(BaseModel):
    content: list[McpContent]
    is_error: bool = False

    @property
    def text(self) -> str:
        return "\n".join(c.text or "" for c in self.content if c.type == "text")
