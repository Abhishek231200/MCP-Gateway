"""FastAPI application factory and startup/shutdown lifecycle."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mcp_gateway.config import settings
from mcp_gateway.middleware.auth import ApiKeyMiddleware
from mcp_gateway.routers import audit, health, registry, tools, workflows

# ─── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(level=settings.log_level.upper())
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if not settings.is_production
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level.upper())
    ),
)
logger = structlog.get_logger()


# ─── Lifespan ─────────────────────────────────────────────────────────────────

async def _recover_interrupted_workflows() -> None:
    """Mark any workflows stuck in non-terminal states as failed.

    These are left behind when the server restarts while a background task is running.
    """
    from datetime import UTC, datetime
    from sqlalchemy import update
    from mcp_gateway.database import AsyncSessionLocal
    from mcp_gateway.models.workflow import Workflow, WorkflowStatus

    interrupted = {WorkflowStatus.PENDING, WorkflowStatus.PLANNING, WorkflowStatus.RUNNING}
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Workflow)
            .where(Workflow.status.in_(interrupted))
            .values(
                status=WorkflowStatus.FAILED,
                error_message="Interrupted by server restart.",
                completed_at=datetime.now(UTC),
            )
        )
        await db.commit()
    logger.info("startup.recovered_interrupted_workflows")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("MCP Gateway starting", environment=settings.environment)

    if settings.environment != "test":
        await _recover_interrupted_workflows()

    scheduler_task: asyncio.Task[None] | None = None
    if settings.environment != "test":
        from mcp_gateway.services.health_scheduler import health_check_loop
        scheduler_task = asyncio.create_task(health_check_loop())

    yield

    if scheduler_task:
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task
    logger.info("MCP Gateway shutting down")


# ─── Application factory ──────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="MCP Gateway",
        description="A Secure Agentic AI Orchestration Platform via Model Context Protocol",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ApiKeyMiddleware)

    app.include_router(health.router)
    app.include_router(registry.router)
    app.include_router(tools.router)
    app.include_router(workflows.router)
    app.include_router(audit.router)

    return app


app = create_app()
