# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP Gateway is a secure agentic AI orchestration platform. A Turborepo monorepo with two apps:
- `apps/api` — FastAPI backend (Python 3.12)
- `apps/web` — React 18 frontend (TypeScript)

## Development Commands

### Start everything (recommended)
```bash
cp .env.example .env   # first time only
docker compose up --build
# API:  http://localhost:8000  (docs at /docs)
# Web:  http://localhost:5173
```

### Backend (`apps/api/`)
All commands run from `apps/api/`.

```bash
# Install
pip install -e ".[dev]"

# Run dev server (hot-reload)
uvicorn mcp_gateway.main:app --reload --reload-dir src

# Lint & format
ruff check src tests
ruff format src tests

# Type check
mypy src

# Run all tests
pytest

# Run a single test file
pytest tests/test_health.py -v

# Run a single test
pytest tests/test_health.py::test_liveness -v

# Run with coverage
pytest --cov=mcp_gateway --cov-report=term-missing

# Database migrations
alembic upgrade head           # apply all migrations
alembic revision --autogenerate -m "description"  # generate new migration
alembic downgrade -1           # roll back one
```

### Frontend (`apps/web/`)
All commands run from `apps/web/`.

```bash
npm install
npm run dev        # Vite dev server at :5173 with /api proxy to :8000
npm run build      # TypeScript compile + Vite build
npm run typecheck  # tsc --noEmit only
npm run lint       # eslint
```

### Monorepo (root)
```bash
npm run dev    # turbo: starts dev servers in both apps in parallel
npm run build  # turbo: builds both apps
npm run test   # turbo: runs both test suites
npm run lint   # turbo: lints both apps
```

## Architecture

### Request flow
```
User → React (Vite :5173)
         └─ /api/* proxy → FastAPI (:8000)
                              ├─ Security Gateway (OPA policies)  [Week 7]
                              ├─ MCP Registry                      [Week 2]
                              └─ Agent Orchestrator (LangGraph)    [Week 5]
                                    └─ MCP Server Adapters         [Week 3-4]
                                          ├─ GitHub MCP
                                          ├─ Slack MCP
                                          ├─ Google Drive MCP
                                          └─ Knowledge Base MCP (RAG)
```

### Backend structure (`apps/api/src/mcp_gateway/`)

- **`config.py`** — single `Settings` object (Pydantic Settings) read from `.env`. Import `settings` everywhere instead of `os.getenv`.
- **`database.py`** — async SQLAlchemy engine + `AsyncSessionLocal`. `pool_pre_ping=True` is set; `echo=settings.debug` logs all SQL when `DEBUG=true`. Use `get_db` as a FastAPI `Depends` to get a session; commits on success, rolls back on exception.
- **`main.py`** — `create_app()` factory. Uses `structlog` for structured logging (dev: colored console, prod: JSON). Add new routers via `app.include_router(...)`.
- **`models/`** — SQLAlchemy ORM models. All models are imported in `models/__init__.py` — **required** for Alembic `autogenerate` to detect schema changes.
- **`routers/`** — one file per feature domain (`health.py`; add `registry.py`, `workflows.py` as features are built).

### Database schema (PostgreSQL)

Five tables, all using UUID PKs:
- `mcp_servers` + `server_capabilities` — MCP Registry (servers and their tools)
- `workflows` + `workflow_steps` — execution tracking (plan, per-step status, token usage)
- `audit_logs` — **append-only**; every tool call and security decision is written here, never updated

Migrations live in `apps/api/alembic/versions/`. The Alembic env uses an async engine matching the app's asyncpg driver.

### Frontend structure (`apps/web/src/`)

- **`main.tsx`** — mounts React with `BrowserRouter`, `QueryClientProvider` (TanStack Query)
- **`App.tsx`** — route definitions; all routes render inside `<Layout>`
- **`components/layout/`** — `Sidebar` (nav links), `Topbar` (page title + API health dot), `Layout` (wraps `<Outlet>`)
- **`pages/`** — one file per route; `DashboardPage` polls `/health` via `useHealthCheck`
- **`hooks/`** — React Query hooks that wrap Axios calls to `/api/*`

Tailwind utility classes are in `index.css` under `@layer components` (`.card`, `.badge-healthy`, etc.). Use these rather than repeating the same class strings.

The Vite dev server proxies `/api/*` → `http://localhost:8000`, stripping the `/api` prefix. All Axios calls in hooks should use `/api/...` paths.

### Adding a new backend feature (pattern)
1. Add ORM model in `models/<domain>.py`, export from `models/__init__.py`
2. Generate migration: `alembic revision --autogenerate -m "add <domain>"`
3. Add router in `routers/<domain>.py`, register in `main.py`
4. Add corresponding React Query hook in `hooks/use<Domain>.ts`
5. Build the page component in `pages/<Domain>Page.tsx`, add route to `App.tsx`

## Environment

Key `.env` variables (see `.env.example` for full list):
- `DATABASE_URL` — asyncpg URL; automatically overridden in Docker Compose to point at the `postgres` service
- `REDIS_URL` — used for rate limiting and pub/sub
- `ENVIRONMENT` — `development` | `test` | `production` (disables `/docs` and `/redoc` in production)
- `DEBUG=true` — enables SQLAlchemy query logging

## Known Gotchas

These have already bitten us — don't repeat them:

- **`CORS_ORIGINS` must be JSON in `.env`** — pydantic-settings v2 runs `json.loads()` on `list[str]` fields *before* any validator runs. A comma-separated string causes a `SettingsError` at startup. Always use: `CORS_ORIGINS=["http://localhost:5173","http://localhost:3000"]`

- **Docker inter-container networking uses service names** — inside Docker Compose, `localhost` resolves to the container itself. Use the Compose service name: `http://api:8000`, `postgresql+asyncpg://mcp_user:mcp_password@postgres:5432/mcp_gateway`, `redis://redis:6379/0`. The `DATABASE_URL` and `REDIS_URL` overrides in `docker-compose.yml` already handle this for the API; don't change them to `localhost`.

- **Editable install needs `src/` to exist** — the API Dockerfile creates a stub `src/mcp_gateway/__init__.py` before running `pip install -e ".[dev]"` so setuptools can resolve the package root. The real source is copied/mounted afterwards. Do not remove this step.

- **`pyproject.toml` build-backend must be `setuptools.build_meta`** — `setuptools.backends.legacy:build` requires setuptools ≥ 69 which isn't bundled in `python:3.12-slim`. Keep `build-backend = "setuptools.build_meta"`.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to `main`/`develop`:
1. **api** job — spins up real Postgres + Redis services, runs ruff → mypy → alembic upgrade → pytest
2. **web** job — eslint → tsc → vite build
3. **docker** job — smoke-builds both production Docker images (runs only on push, after api+web pass)
