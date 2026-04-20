"""Background health-check scheduler — probes active MCP servers every 60 s."""

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import structlog
from sqlalchemy import select

from mcp_gateway.database import AsyncSessionLocal
from mcp_gateway.models.registry import HealthStatus, McpServer
from mcp_gateway.services.cache import cache_invalidate, cache_invalidate_prefix

logger = structlog.get_logger()

CHECK_INTERVAL: int = 60  # seconds; override in tests


async def _probe(base_url: str) -> HealthStatus:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(base_url)
        if resp.status_code < 400:
            return HealthStatus.HEALTHY
        return HealthStatus.DEGRADED
    except Exception:
        return HealthStatus.UNHEALTHY


async def run_checks() -> None:
    """Probe all active servers and persist updated health statuses."""
    # 1. Fetch server stubs (id, name, base_url) — brief connection
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(McpServer.id, McpServer.name, McpServer.base_url)
                .where(McpServer.is_active == True)  # noqa: E712
            )
        ).all()

    if not rows:
        return

    # 2. Probe each server without holding a DB connection
    results: list[tuple[uuid.UUID, str, HealthStatus]] = []
    for server_id, name, base_url in rows:
        status = await _probe(base_url)
        results.append((server_id, name, status))
        logger.info("health_check.done", server=name, status=status.value)

    # 3. Persist results
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as db:
        for server_id, _, status in results:
            server = await db.get(McpServer, server_id)
            if server:
                server.health_status = status
                server.last_health_check = now
        await db.commit()

    # 4. Bust cache for all checked servers
    await cache_invalidate_prefix("registry:servers", "registry:tools")
    exact_keys = [f"registry:server:{sid}" for sid, _, _ in results]
    if exact_keys:
        await cache_invalidate(*exact_keys)


async def health_check_loop() -> None:
    logger.info("health_scheduler.started", interval_seconds=CHECK_INTERVAL)
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            await run_checks()
        except Exception:
            logger.exception("health_scheduler.error")
