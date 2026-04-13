"""Health check endpoints for liveness, readiness, and dependency status."""

import time

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_gateway.config import settings
from mcp_gateway.database import get_db

router = APIRouter(prefix="/health", tags=["health"])

_start_time = time.time()


class DependencyStatus(BaseModel):
    status: str
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    uptime_seconds: float
    dependencies: dict[str, DependencyStatus]


@router.get("", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """Full health check — verifies PostgreSQL and Redis connectivity."""
    deps: dict[str, DependencyStatus] = {}

    # PostgreSQL check
    t0 = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        deps["postgres"] = DependencyStatus(
            status="healthy",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
    except Exception as exc:
        deps["postgres"] = DependencyStatus(status="unhealthy", detail=str(exc))

    # Redis check
    t0 = time.perf_counter()
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        await r.aclose()
        deps["redis"] = DependencyStatus(
            status="healthy",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
    except Exception as exc:
        deps["redis"] = DependencyStatus(status="unhealthy", detail=str(exc))

    overall = "healthy" if all(d.status == "healthy" for d in deps.values()) else "degraded"

    return HealthResponse(
        status=overall,
        version="0.1.0",
        environment=settings.environment,
        uptime_seconds=round(time.time() - _start_time, 2),
        dependencies=deps,
    )


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    """Kubernetes liveness probe — always returns 200 if the process is alive."""
    return {"status": "alive"}


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Kubernetes readiness probe — returns 200 only if DB is reachable."""
    await db.execute(text("SELECT 1"))
    return {"status": "ready"}
