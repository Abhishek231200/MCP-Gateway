"""FastAPI application factory and startup/shutdown lifecycle."""

import logging

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mcp_gateway.config import settings
from mcp_gateway.routers import health

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

# ─── Application factory ──────────────────────────────────────────────────────


def create_app() -> FastAPI:
    app = FastAPI(
        title="MCP Gateway",
        description="A Secure Agentic AI Orchestration Platform via Model Context Protocol",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(health.router)

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("MCP Gateway starting", environment=settings.environment)

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        logger.info("MCP Gateway shutting down")

    return app


app = create_app()
