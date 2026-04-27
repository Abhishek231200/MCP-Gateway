"""MCP Registry CRUD endpoints and tool-search / capability-indexing API."""

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_gateway.database import get_db
from mcp_gateway.schemas.registry import (
    CapabilityCreate,
    ServerCreate,
    ServerListResponse,
    ServerUpdate,
    ServerWithCapabilities,
    ToolListResponse,
    ToolSearchResult,
)
from mcp_gateway.services import registry as svc
from mcp_gateway.services.cache import cache_get, cache_set

logger = structlog.get_logger()
router = APIRouter(prefix="/registry", tags=["registry"])

_CACHE_TTL = 60


# ── Server CRUD ───────────────────────────────────────────────────────────────

@router.post(
    "/servers",
    response_model=ServerWithCapabilities,
    status_code=status.HTTP_201_CREATED,
)
async def register_server(
    payload: ServerCreate,
    db: AsyncSession = Depends(get_db),
) -> ServerWithCapabilities:
    if await svc.get_server_by_name(db, payload.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Server '{payload.name}' is already registered.",
        )
    server = await svc.create_server(db, payload)
    return ServerWithCapabilities.model_validate(server)


@router.get("/servers", response_model=ServerListResponse)
async def list_servers(
    active_only: bool = Query(True, description="Return only active servers"),
    health_status: str | None = Query(None, description="Filter by health status"),
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_db),
) -> ServerListResponse:
    cache_key = f"registry:servers:active={active_only}:hs={health_status}:l={limit}:o={offset}"
    cached = await cache_get(cache_key)
    if cached:
        return ServerListResponse(**cached)

    servers, total = await svc.list_servers(
        db, active_only=active_only, health_status=health_status, limit=limit, offset=offset
    )
    response = ServerListResponse(
        total=total,
        items=[ServerWithCapabilities.model_validate(s) for s in servers],
    )
    await cache_set(cache_key, response.model_dump(mode="json"), ttl=_CACHE_TTL)
    return response


@router.get("/servers/{server_id}", response_model=ServerWithCapabilities)
async def get_server(
    server_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ServerWithCapabilities:
    cache_key = f"registry:server:{server_id}"
    cached = await cache_get(cache_key)
    if cached:
        return ServerWithCapabilities(**cached)

    server = await svc.get_server(db, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found.")
    response = ServerWithCapabilities.model_validate(server)
    await cache_set(cache_key, response.model_dump(mode="json"), ttl=_CACHE_TTL)
    return response


@router.patch("/servers/{server_id}", response_model=ServerWithCapabilities)
async def update_server(
    server_id: uuid.UUID,
    payload: ServerUpdate,
    db: AsyncSession = Depends(get_db),
) -> ServerWithCapabilities:
    server = await svc.update_server(db, server_id, payload)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found.")
    return ServerWithCapabilities.model_validate(server)


@router.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deregister_server(
    server_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    deleted = await svc.deregister_server(db, server_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found.")


# ── Capabilities ──────────────────────────────────────────────────────────────

@router.put(
    "/servers/{server_id}/capabilities",
    response_model=ServerWithCapabilities,
    summary="Replace all capabilities for a server",
)
async def replace_capabilities(
    server_id: uuid.UUID,
    capabilities: list[CapabilityCreate],
    db: AsyncSession = Depends(get_db),
) -> ServerWithCapabilities:
    server = await svc.replace_capabilities(db, server_id, capabilities)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found.")
    return ServerWithCapabilities.model_validate(server)


# ── Capability index / tool search ────────────────────────────────────────────

@router.get("/tools", response_model=ToolListResponse)
async def search_tools(
    name: str | None = Query(None, description="Partial match on tool_name"),
    permission: str | None = Query(None, description="Filter by required_permission"),
    active_servers_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
) -> ToolListResponse:
    cache_key = f"registry:tools:name={name}:perm={permission}:active={active_servers_only}"
    cached = await cache_get(cache_key)
    if cached:
        return ToolListResponse(**cached)

    rows = await svc.list_tools(
        db,
        tool_name=name,
        required_permission=permission,
        active_servers_only=active_servers_only,
    )
    items = [
        ToolSearchResult(
            server_id=server.id,
            server_name=server.name,
            server_display_name=server.display_name,
            health_status=server.health_status,
            tool_name=cap.tool_name,
            description=cap.description,
            input_schema=cap.input_schema,
            output_schema=cap.output_schema,
            required_permission=cap.required_permission,
            avg_latency_ms=cap.avg_latency_ms,
        )
        for server, cap in rows
    ]
    response = ToolListResponse(total=len(items), items=items)
    await cache_set(cache_key, response.model_dump(mode="json"), ttl=_CACHE_TTL)
    return response
