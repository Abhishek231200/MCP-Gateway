"""Pydantic schemas for tool invocation endpoints."""

import uuid
from typing import Any

from pydantic import BaseModel, Field


class InvokeRequest(BaseModel):
    server_id: uuid.UUID
    tool_name: str = Field(min_length=1, max_length=256)
    arguments: dict[str, Any] = Field(default_factory=dict)
    actor: str = Field(default="api", max_length=256)


class InvokeResponse(BaseModel):
    result: Any
    latency_ms: int
    server_name: str
    tool_name: str
    adapter_type: str
