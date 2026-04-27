"""Registry service — DB operations for MCP server CRUD and capability indexing."""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mcp_gateway.models.audit import AuditLog
from mcp_gateway.models.registry import McpServer, ServerCapability
from mcp_gateway.schemas.registry import CapabilityCreate, ServerCreate, ServerUpdate
from mcp_gateway.services.cache import cache_invalidate, cache_invalidate_prefix

logger = structlog.get_logger()

_LIST_KEY = "registry:servers"
_TOOLS_KEY = "registry:tools"


def _server_key(server_id: uuid.UUID) -> str:
    return f"registry:server:{server_id}"


async def _bust_cache(server_id: uuid.UUID | None = None) -> None:
    # Prefix-based bust covers all query-param variants of list/tools keys
    await cache_invalidate_prefix(_LIST_KEY, _TOOLS_KEY)
    if server_id:
        await cache_invalidate(_server_key(server_id))


# ── Reads ──────────────────────────────────────────────────────────────────────

async def get_server(db: AsyncSession, server_id: uuid.UUID) -> McpServer | None:
    result = await db.execute(
        select(McpServer)
        .where(McpServer.id == server_id)
        .options(selectinload(McpServer.capabilities))
    )
    return result.scalar_one_or_none()


async def get_server_by_name(db: AsyncSession, name: str) -> McpServer | None:
    result = await db.execute(select(McpServer).where(McpServer.name == name))
    return result.scalar_one_or_none()


async def list_servers(
    db: AsyncSession,
    *,
    active_only: bool = True,
    health_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[McpServer], int]:
    stmt = select(McpServer).options(selectinload(McpServer.capabilities))
    if active_only:
        stmt = stmt.where(McpServer.is_active == True)  # noqa: E712
    if health_status:
        stmt = stmt.where(McpServer.health_status == health_status)
    count_stmt = stmt.with_only_columns(McpServer.id)
    total = len((await db.execute(count_stmt)).all())
    stmt = stmt.order_by(McpServer.name).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def list_tools(
    db: AsyncSession,
    *,
    tool_name: str | None = None,
    required_permission: str | None = None,
    active_servers_only: bool = True,
) -> list[tuple[McpServer, ServerCapability]]:
    stmt = (
        select(McpServer, ServerCapability)
        .join(ServerCapability, ServerCapability.server_id == McpServer.id)
        .where(ServerCapability.is_active == True)  # noqa: E712
    )
    if active_servers_only:
        stmt = stmt.where(McpServer.is_active == True)  # noqa: E712
    if tool_name:
        stmt = stmt.where(ServerCapability.tool_name.ilike(f"%{tool_name}%"))
    if required_permission:
        stmt = stmt.where(ServerCapability.required_permission == required_permission)
    stmt = stmt.order_by(McpServer.name, ServerCapability.tool_name)
    result = await db.execute(stmt)
    return result.tuples().all()


# ── Writes ─────────────────────────────────────────────────────────────────────

async def create_server(db: AsyncSession, payload: ServerCreate, actor: str = "api") -> McpServer:
    server = McpServer(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        base_url=payload.base_url,
        version=payload.version,
        auth_type=payload.auth_type,
        auth_config=payload.auth_config,
        metadata_=payload.metadata,
    )
    db.add(server)
    await db.flush()  # populate server.id before adding capabilities

    for cap in payload.capabilities:
        db.add(ServerCapability(
            server_id=server.id,
            tool_name=cap.tool_name,
            description=cap.description,
            input_schema=cap.input_schema,
            output_schema=cap.output_schema,
            required_permission=cap.required_permission,
        ))

    db.add(AuditLog(
        action="server_registered",
        actor=actor,
        server_name=server.name,
        request_payload={"name": server.name, "base_url": server.base_url},
    ))

    await db.flush()
    await db.refresh(server, ["capabilities"])
    await _bust_cache()
    logger.info("registry.server_created", name=server.name, id=str(server.id))
    return server


async def update_server(
    db: AsyncSession, server_id: uuid.UUID, payload: ServerUpdate
) -> McpServer | None:
    server = await get_server(db, server_id)
    if server is None:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    # `metadata` in payload → `metadata_` on ORM model
    if "metadata" in update_data:
        server.metadata_ = update_data.pop("metadata")
    for field, value in update_data.items():
        setattr(server, field, value)

    server.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(server, ["capabilities"])
    await _bust_cache(server_id)
    logger.info("registry.server_updated", name=server.name, id=str(server_id))
    return server


async def deregister_server(
    db: AsyncSession, server_id: uuid.UUID, actor: str = "api"
) -> bool:
    server = await get_server(db, server_id)
    if server is None:
        return False

    db.add(AuditLog(
        action="server_deregistered",
        actor=actor,
        server_name=server.name,
        request_payload={"server_id": str(server_id)},
    ))
    await db.delete(server)
    await db.flush()
    await _bust_cache(server_id)
    logger.info("registry.server_deregistered", name=server.name, id=str(server_id))
    return True


async def replace_capabilities(
    db: AsyncSession, server_id: uuid.UUID, capabilities: list[CapabilityCreate]
) -> McpServer | None:
    server = await get_server(db, server_id)
    if server is None:
        return None

    # Delete existing capabilities, replace with new set
    for cap in list(server.capabilities):
        await db.delete(cap)
    await db.flush()

    for new_cap in capabilities:
        db.add(ServerCapability(
            server_id=server_id,
            tool_name=new_cap.tool_name,
            description=new_cap.description,
            input_schema=new_cap.input_schema,
            output_schema=new_cap.output_schema,
            required_permission=new_cap.required_permission,
        ))

    await db.flush()
    await db.refresh(server, ["capabilities"])
    await _bust_cache(server_id)
    return server
