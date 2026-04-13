"""Shared pytest fixtures for the API test suite."""

import pytest
from httpx import ASGITransport, AsyncClient

from mcp_gateway.main import app


@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
