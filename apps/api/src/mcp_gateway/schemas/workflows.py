"""Pydantic schemas for workflow creation, listing, and detail endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mcp_gateway.models.workflow import StepStatus, WorkflowStatus


class WorkflowCreate(BaseModel):
    task: str = Field(min_length=1, max_length=4096, description="Natural-language task to execute")
    actor: str = Field(default="user", max_length=256)
    conversation_id: uuid.UUID | None = Field(default=None, description="Root workflow ID to group follow-up messages")


class WorkflowStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    step_order: int
    agent_role: str
    server_name: str | None
    tool_name: str | None
    status: StepStatus
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None
    error_message: str | None
    tokens_used: int
    latency_ms: int | None
    created_at: datetime
    completed_at: datetime | None


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task: str
    initiated_by: str
    status: WorkflowStatus
    plan: dict[str, Any]
    result: dict[str, Any] | None
    error_message: str | None
    total_tokens_used: int
    conversation_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    steps: list[WorkflowStepResponse] = Field(default_factory=list)


class WorkflowListResponse(BaseModel):
    total: int
    items: list[WorkflowResponse]
