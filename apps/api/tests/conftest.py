"""Shared pytest fixtures for the API test suite."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from mcp_gateway.config import settings
from mcp_gateway.database import get_db
from mcp_gateway.main import app  # noqa: E402  (app import triggers logging setup)

# ── Basic client (no DB override — for health tests) ──────────────────────────

@pytest.fixture
async def client() -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── DB fixtures for integration tests ─────────────────────────────────────────

@pytest.fixture(scope="session")
async def test_engine():
    """Session-scoped engine; skips if Postgres is unreachable."""
    engine = create_async_engine(settings.database_url, echo=False)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("PostgreSQL not reachable — skipping integration tests")
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncSession:
    """
    Function-scoped session wrapped in a rolled-back transaction so each test
    starts with a clean slate without touching real data.
    """
    conn = await test_engine.connect()
    await conn.begin()
    session = AsyncSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    yield session
    await conn.rollback()
    await conn.close()


@pytest.fixture
async def registry_client(db_session: AsyncSession) -> AsyncClient:
    """AsyncClient with get_db overridden to use the test transaction session."""
    async def _override() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
