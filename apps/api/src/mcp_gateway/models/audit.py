"""AuditLog model — immutable record of every tool invocation."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mcp_gateway.database import Base


class AuditAction(StrEnum):
    TOOL_CALL = "tool_call"
    TOOL_BLOCKED = "tool_blocked"
    RATE_LIMITED = "rate_limited"
    INJECTION_DETECTED = "injection_detected"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    SERVER_REGISTERED = "server_registered"
    SERVER_DEREGISTERED = "server_deregistered"


class AuditLog(Base):
    """Immutable audit trail entry.

    Written on every tool invocation, security decision, and workflow event.
    Never updated after insert — use append-only semantics.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Nullable FKs so log entries survive cascade deletes on parent tables
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_steps.id", ondelete="SET NULL"),
        nullable=True,
    )

    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, index=True
    )
    # Actor: "agent:<role>", "user:<id>", "system"
    actor: Mapped[str] = mapped_column(String(256), nullable=False, index=True)

    server_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    tool_name: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)

    # Full request / response payloads for replay and debugging
    request_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    response_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Security gateway decision
    allowed: Mapped[bool | None] = mapped_column(nullable=True)
    policy_decision: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ISO timestamp — indexed for time-range queries in the dashboard
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog action={self.action} actor={self.actor!r} "
            f"tool={self.tool_name!r} allowed={self.allowed}>"
        )
