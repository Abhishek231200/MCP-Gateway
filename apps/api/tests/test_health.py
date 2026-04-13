"""Tests for health check endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_health_endpoint_shape(client: AsyncClient) -> None:
    """Health endpoint returns expected top-level keys (DB/Redis may be unreachable in unit tests)."""
    response = await client.get("/health")
    data = response.json()
    assert "status" in data
    assert "version" in data
    assert "environment" in data
    assert "uptime_seconds" in data
    assert "dependencies" in data
