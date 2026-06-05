"""Pydantic schemas for the audit log API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID | None
    action: str
    actor: str
    server_name: str | None
    tool_name: str | None
    allowed: bool | None
    policy_decision: dict[str, Any] | None
    latency_ms: int | None
    created_at: datetime
    entry_hash: str | None
    prev_hash: str | None


class AuditLogListResponse(BaseModel):
    total: int
    items: list[AuditLogResponse]


class AuditStatsResponse(BaseModel):
    total: int
    blocked_today: int
    tool_calls_today: int
    chain_valid: bool
    last_entry_hash: str | None
