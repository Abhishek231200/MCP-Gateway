"""Tools router — invoke MCP server tools via the adapter layer."""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_gateway.database import get_db
from mcp_gateway.models.registry import McpServer, ServerCapability
from mcp_gateway.schemas.tools import InvokeRequest, InvokeResponse
from mcp_gateway.services.adapters import (
    AdapterError,
    AdapterNotFoundError,
    get_adapter,
)
from mcp_gateway.services.adapters.credentials import CredentialResolutionError

logger = structlog.get_logger()

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/invoke", response_model=InvokeResponse)
async def invoke_tool(
    payload: InvokeRequest,
    db: AsyncSession = Depends(get_db),
) -> InvokeResponse:
    """Invoke a tool on a registered MCP server.

    Validates that the server and tool exist, selects the correct adapter,
    executes the tool, and writes an audit log entry.
    """
    # 1. Load the server
    result = await db.execute(
        select(McpServer).where(McpServer.id == payload.server_id)
    )
    server = result.scalar_one_or_none()
    if server is None or not server.is_active:
        raise HTTPException(status_code=404, detail="Server not found or inactive")

    # 2. Validate the tool is registered
    cap_result = await db.execute(
        select(ServerCapability)
        .where(ServerCapability.server_id == server.id)
        .where(ServerCapability.tool_name == payload.tool_name)
        .where(ServerCapability.is_active == True)  # noqa: E712
    )
    if cap_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=422,
            detail=f"Tool '{payload.tool_name}' is not registered for server '{server.name}'",
        )

    # 3. Get the adapter
    try:
        adapter = get_adapter(server)
    except AdapterNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # 4. Invoke
    try:
        tool_result = await adapter.invoke_tool(
            server=server,
            tool_name=payload.tool_name,
            arguments=payload.arguments,
            db=db,
            actor=payload.actor,
        )
    except CredentialResolutionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AdapterError as exc:
        status = exc.status_code or 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    return InvokeResponse(
        result=tool_result["result"],
        latency_ms=tool_result["latency_ms"],
        server_name=server.name,
        tool_name=payload.tool_name,
        adapter_type=tool_result["metadata"]["adapter_type"],
    )
