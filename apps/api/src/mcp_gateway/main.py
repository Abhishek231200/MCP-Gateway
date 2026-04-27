"""FastAPI application factory and startup/shutdown lifecycle."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mcp_gateway.config import settings
from mcp_gateway.routers import health, registry, tools

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

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("MCP Gateway starting", environment=settings.environment)

    scheduler_task: asyncio.Task | None = None
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

    app.include_router(health.router)
    app.include_router(registry.router)
    app.include_router(tools.router)

    return app


app = create_app()
