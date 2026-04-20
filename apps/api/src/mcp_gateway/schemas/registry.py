"""Pydantic schemas for the MCP Registry API."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from mcp_gateway.models.registry import AuthType, HealthStatus


class CapabilityCreate(BaseModel):
    tool_name: str = Field(..., max_length=256)
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_permission: str = Field(default="read", pattern="^(read|write|admin)$")


class CapabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    server_id: uuid.UUID
    tool_name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_permission: str
    is_active: bool
    avg_latency_ms: int | None
    created_at: datetime


class ServerCreate(BaseModel):
    name: str = Field(..., max_length=128, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    display_name: str = Field(..., max_length=256)
    description: str | None = None
    base_url: str = Field(..., max_length=2048)
    version: str = Field(default="1.0.0", max_length=32)
    auth_type: AuthType = AuthType.NONE
    auth_config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[CapabilityCreate] = Field(default_factory=list)


class ServerUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=256)
    description: str | None = None
    base_url: str | None = Field(None, max_length=2048)
    version: str | None = Field(None, max_length=32)
    auth_type: AuthType | None = None
    auth_config: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool | None = None


class ServerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    name: str
    display_name: str
    description: str | None
    base_url: str
    version: str
    auth_type: AuthType
    health_status: HealthStatus
    last_health_check: datetime | None
    is_active: bool
    # ORM column is `metadata_` (avoids SQLAlchemy name clash); both aliases accepted
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata_", "metadata"),
    )
    created_at: datetime
    updated_at: datetime


class ServerWithCapabilities(ServerResponse):
    capabilities: list[CapabilityResponse] = []


class ToolSearchResult(BaseModel):
    server_id: uuid.UUID
    server_name: str
    server_display_name: str
    health_status: HealthStatus
    tool_name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_permission: str
    avg_latency_ms: int | None


class ServerListResponse(BaseModel):
    total: int
    items: list[ServerWithCapabilities]


class ToolListResponse(BaseModel):
    total: int
    items: list[ToolSearchResult]
