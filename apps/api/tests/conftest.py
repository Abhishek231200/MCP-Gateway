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

# Names used by test data — cleaned up after each test
_TEST_SERVER_NAMES = (
    "github-mcp-test",
    "bare-server-test",
    "github-mcp",
    "slack-mcp",
)


def _check_pg_reachable(url: str) -> bool:
    """Synchronous reachability check run at collection time."""
    import asyncio
    async def _probe():
        engine = create_async_engine(url, echo=False)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()
    return asyncio.get_event_loop().run_until_complete(_probe())


@pytest.fixture
async def db_session():
    """
    Function-scoped session backed by its own engine connection.
    Each test gets a fresh connection; teardown deletes inserted test rows.
    Skips automatically when Postgres is unreachable.
    """
    engine = create_async_engine(settings.database_url, echo=False)
    try:
        async with engine.connect() as probe:
            await probe.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("PostgreSQL not reachable — skipping integration tests")
        return

    session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield session
        # Best-effort cleanup of test rows
        try:
            names_tuple = ", ".join(f"'{n}'" for n in _TEST_SERVER_NAMES)
            await session.execute(
                text(f"DELETE FROM audit_logs WHERE server_name IN ({names_tuple})")
            )
            await session.execute(
                text(f"DELETE FROM server_capabilities USING mcp_servers "
                     f"WHERE server_capabilities.server_id = mcp_servers.id "
                     f"AND mcp_servers.name IN ({names_tuple})")
            )
            await session.execute(
                text(f"DELETE FROM mcp_servers WHERE name IN ({names_tuple})")
            )
            await session.commit()
        except Exception:
            await session.rollback()
    finally:
        await session.close()
        await engine.dispose()


@pytest.fixture
async def registry_client(db_session: AsyncSession) -> AsyncClient:
    """AsyncClient with get_db overridden to use the test session."""
    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
