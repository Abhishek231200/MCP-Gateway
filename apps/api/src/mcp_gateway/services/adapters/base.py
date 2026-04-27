"""BaseAdapter ABC — contract every MCP server adapter must implement."""

import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, TypedDict

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_gateway.models.audit import AuditAction, AuditLog
from mcp_gateway.models.registry import McpServer, ServerCapability

logger = structlog.get_logger()


class ToolResult(TypedDict):
    result: Any
    latency_ms: int
    metadata: dict[str, Any]


class AdapterError(Exception):
    """Raised when an adapter call fails (network, auth, invalid tool, etc.)."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AdapterNotFoundError(AdapterError):
    """Raised by get_adapter when no adapter matches the server's adapter_type."""


class BaseAdapter(ABC):
    """Abstract base for all MCP server adapters.

    Subclasses implement _execute_tool and _get_tool_definitions.
    invoke_tool handles timing, credential injection, audit log writes,
    and avg_latency_ms updates — subclasses never touch those concerns.
    """

    @property
    @abstractmethod
    def adapter_type(self) -> str:
        """Machine-readable type string, e.g. 'github'. Must match metadata_.adapter_type."""
        ...

    @abstractmethod
    async def _execute_tool(
        self,
        server: McpServer,
        tool_name: str,
        arguments: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        """Perform the actual tool call and return a normalized result.

        Raise AdapterError on failure. Do NOT write audit logs here.
        """
        ...

    @abstractmethod
    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return static tool definitions for this adapter.

        Each dict: tool_name, description, input_schema, output_schema, required_permission.
        """
        ...

    async def list_tools(self, server: McpServer) -> list[dict[str, Any]]:
        """Return this adapter's tool manifest (no DB or network call)."""
        return self._get_tool_definitions()

    async def invoke_tool(
        self,
        server: McpServer,
        tool_name: str,
        arguments: dict[str, Any],
        db: AsyncSession,
        actor: str = "system",
    ) -> ToolResult:
        from mcp_gateway.services.adapters.credentials import resolve_credentials

        headers = resolve_credentials(server)

        t0 = time.perf_counter()
        error: Exception | None = None
        result: Any = None

        try:
            result = await self._execute_tool(server, tool_name, arguments, headers)
        except AdapterError as exc:
            error = exc

        latency_ms = round((time.perf_counter() - t0) * 1000)
        action = AuditAction.TOOL_BLOCKED if error else AuditAction.TOOL_CALL
        db.add(
            AuditLog(
                action=action,
                actor=actor,
                server_name=server.name,
                tool_name=tool_name,
                request_payload={"arguments": arguments},
                response_payload=(
                    {"result": result} if error is None else {"error": str(error)}
                ),
                allowed=error is None,
                latency_ms=latency_ms,
            )
        )
        await db.flush()

        if error is None:
            await _update_latency(db, server.id, tool_name, latency_ms)

        logger.info(
            "adapter.tool_call",
            adapter=self.adapter_type,
            server=server.name,
            tool=tool_name,
            latency_ms=latency_ms,
            success=error is None,
        )

        if error is not None:
            raise error

        return ToolResult(
            result=result,
            latency_ms=latency_ms,
            metadata={
                "server_name": server.name,
                "tool_name": tool_name,
                "adapter_type": self.adapter_type,
            },
        )


async def _update_latency(
    db: AsyncSession,
    server_id: uuid.UUID,
    tool_name: str,
    new_latency_ms: int,
) -> None:
    """Update avg_latency_ms on ServerCapability using EMA (alpha=0.3)."""
    result = await db.execute(
        select(ServerCapability)
        .where(ServerCapability.server_id == server_id)
        .where(ServerCapability.tool_name == tool_name)
        .where(ServerCapability.is_active == True)  # noqa: E712
    )
    cap = result.scalar_one_or_none()
    if cap is None:
        return
    if cap.avg_latency_ms is None:
        cap.avg_latency_ms = new_latency_ms
    else:
        alpha = 0.3
        cap.avg_latency_ms = round(alpha * new_latency_ms + (1 - alpha) * cap.avg_latency_ms)
    await db.flush()
