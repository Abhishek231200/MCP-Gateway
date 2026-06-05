"""Pydantic schemas for the audit log API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str | None
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

    @classmethod
    def model_validate(cls, obj: Any, **kwargs: Any) -> "AuditLogResponse":
        # Coerce UUID fields to str for JSON serialisation
        data = super().model_validate(obj, **kwargs)
        if data.id and not isinstance(data.id, str):
            data.id = str(data.id)
        if data.workflow_id and not isinstance(data.workflow_id, str):
            data.workflow_id = str(data.workflow_id)
        return data


class AuditLogListResponse(BaseModel):
    total: int
    items: list[AuditLogResponse]


class AuditStatsResponse(BaseModel):
    total: int
    blocked_today: int
    tool_calls_today: int
    chain_valid: bool
    last_entry_hash: str | None
