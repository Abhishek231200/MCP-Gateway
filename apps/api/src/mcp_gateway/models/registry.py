"""MCP Registry models — server catalog and capabilities."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mcp_gateway.database import Base


class AuthType(str, enum.Enum):
    NONE = "none"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    JWT = "jwt"


class HealthStatus(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class McpServer(Base):
    """Registered MCP server in the gateway registry."""

    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")

    auth_type: Mapped[AuthType] = mapped_column(
        Enum(AuthType), nullable=False, default=AuthType.NONE
    )
    # Encrypted credential config stored as JSONB (e.g. {"token_env_var": "GITHUB_TOKEN"})
    auth_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    health_status: Mapped[HealthStatus] = mapped_column(
        Enum(HealthStatus), nullable=False, default=HealthStatus.UNKNOWN, index=True
    )
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)

    # Extra metadata (tags, owner, etc.)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    capabilities: Mapped[list["ServerCapability"]] = relationship(
        "ServerCapability", back_populates="server", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<McpServer name={self.name!r} status={self.health_status}>"


class ServerCapability(Base):
    """A specific tool/capability exposed by an MCP server."""

    __tablename__ = "server_capabilities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON Schema for input parameters
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # JSON Schema for output
    output_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Permission level required: "read", "write", "admin"
    required_permission: Mapped[str] = mapped_column(
        String(32), nullable=False, default="read", index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Avg latency in ms from health checks
    avg_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    server: Mapped["McpServer"] = relationship("McpServer", back_populates="capabilities")

    def __repr__(self) -> str:
        return f"<ServerCapability tool={self.tool_name!r} server={self.server_id}>"
