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
- **`routers/`** — one file per feature domain (`health.py`, `registry.py`, `tools.py`; add `workflows.py` as features are built).
- **`schemas/`** — Pydantic request/response models (separate from ORM models). `ServerResponse` uses `validation_alias=AliasChoices("metadata_", "metadata")` to bridge the ORM's `metadata_` field name to the JSON field `metadata`.
- **`services/`** — business logic: `registry.py` (CRUD + cache busting), `cache.py` (Redis get/set/invalidate/invalidate_prefix), `health_scheduler.py` (background asyncio loop), `adapters/` (MCP server adapter layer — see below). Cache busting always uses `cache_invalidate_prefix` for list/tools keys — never exact-key delete.

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

### Adapter Layer (Week 3)

Files live in `services/adapters/`:
- **`base.py`** — `BaseAdapter` ABC + `ToolResult` TypedDict. `invoke_tool(server, tool_name, arguments, db, actor)` handles timing, credential injection, AuditLog write (`db.flush()`), and EMA latency update on `ServerCapability.avg_latency_ms`. Subclasses implement `_execute_tool` and `_get_tool_definitions` only.
- **`credentials.py`** — `resolve_credentials(server) → dict[str, str]`. Reads `auth_config["token_env_var"]` from the server row, fetches the value from `os.environ`, returns an HTTP headers dict. Raises `CredentialResolutionError` (→ 503) if misconfigured — never reads raw tokens from the DB.
- **`github.py`** — `GitHubAdapter`: wraps GitHub REST API v3. 6 tools: `list_repos`, `get_pr`, `list_prs`, `get_issue`, `list_issues`, `get_file_contents`. Each normalizes the GitHub response (drops `node_id`, `performed_via_github_app`, etc.).
- **`registry.py`** — `get_adapter(server) → BaseAdapter`. Dispatches on `server.metadata_["adapter_type"]`. Raises `AdapterNotFoundError` (→ 503) for unknown types. Add Week 4 adapters here: `"slack": SlackAdapter()`, `"gdrive": GoogleDriveAdapter()`.

Tool invocation endpoint: `POST /tools/invoke` (`routers/tools.py`)
- Body: `{server_id, tool_name, arguments, actor?}`
- Validates server exists + tool is registered in `server_capabilities`
- Calls `get_adapter(server)` → `adapter.invoke_tool(...)` → writes `AuditLog`
- Error codes: 404 (unknown server), 422 (unregistered tool), 503 (no adapter / missing credential), 502 (adapter HTTP error)

Registering a server for a specific adapter — set `metadata.adapter_type` at registration time:
```json
{"metadata": {"adapter_type": "github"}, "auth_config": {"token_env_var": "GITHUB_TOKEN"}}
```

Frontend hooks: `useUpdateServer()` (PATCH auth_config), `useInvokeTool()` (POST /tools/invoke). `AuthConfigPanel` component in `RegistryPage` shows token source and allows editing the env var name.

### Registry API (Week 2)

Endpoints under `/registry/`:
- `POST /registry/servers` — register + write audit log (`server_registered`)
- `GET /registry/servers` — paginated list with `active_only` / `health_status` filters (Redis-cached 60 s)
- `GET /registry/servers/{id}` — full server + capabilities (Redis-cached)
- `PATCH /registry/servers/{id}` — partial update (any subset of fields)
- `DELETE /registry/servers/{id}` — hard delete + `server_deregistered` audit entry
- `PUT /registry/servers/{id}/capabilities` — replace entire capability set
- `GET /registry/tools` — cross-server tool search by `name` (ilike) and `permission`

The health-check scheduler (`services/health_scheduler.py`) runs every 60 s as an asyncio background task. It is **not started** when `ENVIRONMENT=test`. It probes each active server's `base_url` via HTTP GET, marks `healthy` / `degraded` / `unhealthy`, and busts the Redis cache.

### Testing

- `client` fixture — no DB override; used for health tests
- `db_session` fixture — function-scoped; creates its own engine connection per test, commits are allowed, cleans up known test server names in teardown. Skips automatically when Postgres is unreachable.
- `registry_client` fixture — `AsyncClient` with `get_db` overridden to use the test session; requires Postgres
- `test_adapters.py` — unit tests only (no DB, mock httpx via `patch`)
- `test_tools_router.py` — integration tests for `POST /tools/invoke`; mocks `_gh_request` so no real GitHub calls
- **Do not use `join_transaction_mode="create_savepoint"`** with asyncpg — it causes `InterfaceError: cannot perform operation: another operation is in progress` when multiple requests share the same connection. Use per-test engines instead (current pattern).

## Known Gotchas

These have already bitten us — don't repeat them:

- **`CORS_ORIGINS` must be JSON in `.env`** — pydantic-settings v2 runs `json.loads()` on `list[str]` fields *before* any validator runs. A comma-separated string causes a `SettingsError` at startup. Always use: `CORS_ORIGINS=["http://localhost:5173","http://localhost:3000"]`

- **Docker inter-container networking uses service names** — inside Docker Compose, `localhost` resolves to the container itself. Use the Compose service name: `http://api:8000`, `postgresql+asyncpg://mcp_user:mcp_password@postgres:5432/mcp_gateway`, `redis://redis:6379/0`. The `DATABASE_URL` and `REDIS_URL` overrides in `docker-compose.yml` already handle this for the API; don't change them to `localhost`.

- **Editable install needs `src/` to exist** — the API Dockerfile creates a stub `src/mcp_gateway/__init__.py` before running `pip install -e ".[dev]"` so setuptools can resolve the package root. The real source is copied/mounted afterwards. Do not remove this step.

- **Alembic + asyncpg enum types: use `op.execute("DO $$ BEGIN CREATE TYPE ... END $$")` + reuse `postgresql.ENUM` variables** — Three rules that all must hold together: (1) Create types via raw SQL `DO $$ BEGIN CREATE TYPE ... EXCEPTION WHEN duplicate_object THEN NULL; END $$` (one `op.execute` per statement — asyncpg rejects multi-statement strings). (2) Declare `postgresql.ENUM(..., create_type=False)` variables for each type. (3) Pass those variables directly as the column type in `op.create_table` — never create a new `sa.Enum(...)` inline, even with `create_type=False`, because SQLAlchemy will still fire `_on_table_create` for new instances. The migration in `alembic/versions/0001_initial_schema.py` demonstrates this pattern.

- **`pyproject.toml` build-backend must be `setuptools.build_meta`** — `setuptools.backends.legacy:build` requires setuptools ≥ 69 which isn't bundled in `python:3.12-slim`. Keep `build-backend = "setuptools.build_meta"`.

- **`Enum(StrEnum)` uses member names, not values** — SQLAlchemy's `Enum(MyStrEnum)` serializes the member *name* (`API_KEY`) not its *value* (`api_key`) to Postgres by default. Always add `values_callable=lambda obj: [e.value for e in obj]` to every `Enum(...)` column using a StrEnum. Without it, every INSERT fails with `invalid input value for enum`.

- **`ServerListResponse` items must include `capabilities`** — use `ServerWithCapabilities` (not `ServerResponse`) when building list items. The frontend `ServerCard` accesses `server.capabilities.length` unconditionally; omitting the field causes a React TypeError that crashes the entire Registry page.

- **Redis cache bust must use prefix scan, not exact key delete** — the list cache key includes query params (e.g. `registry:servers:active=True:hs=None:l=100:o=0`), so `cache_invalidate("registry:servers")` is a no-op. Use `cache_invalidate_prefix("registry:servers", "registry:tools")` in `_bust_cache()` and the health scheduler. `cache_invalidate_prefix` uses `SCAN` + `DELETE` to wipe all matching keys. Without this, mutations (register, deregister, update) appear to do nothing in the UI because the stale list is returned from cache.

- **Use `http://api:8000/health` as a test server base URL** — when registering a test MCP server that needs to show `healthy`, use `http://api:8000/health` as `base_url`. The health scheduler probes from inside Docker so it reaches the API container by service name. `localhost:8000` would resolve to the scheduler container itself and time out.

- **`adapter_type` goes in `metadata` JSONB at registration, not a separate column** — set `"metadata": {"adapter_type": "github"}` in the POST body. No migration needed; `metadata_` JSONB already exists on `mcp_servers`.

- **`db.flush()` in adapters, not `db.commit()`** — `invoke_tool` participates in the caller's request-scoped `get_db` transaction. Using `flush()` writes to the DB within the transaction without committing; the `get_db` dependency commits on success and rolls back on exception.

- **`CredentialResolutionError` (503) vs `AdapterError` (502) are distinct** — `CredentialResolutionError` means misconfiguration (missing env var); return 503 so operators know to fix the server config. `AdapterError` means the upstream API call failed; return 502 (or the upstream status code if available).

- **`npm install` must be run from the monorepo root, not `apps/web/`** — the repo uses npm workspaces; running `npm install` in `apps/web/` alone will not hoist `@tanstack/react-query` and other shared packages to `node_modules/` where the TypeScript server can find them. Always run `npm install` from `/MCP-Gateway/`.

- **`docker-compose.yml` volume mounts `tests/` alongside `src/`** — both `./apps/api/src:/app/src` and `./apps/api/tests:/app/tests` are mounted so test file edits are reflected in the container without a rebuild. If you add a new top-level directory under `apps/api/` that needs to be live-reloaded, add a corresponding volume entry.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on push/PR to `main`/`develop`:
1. **api** job — spins up real Postgres + Redis services, runs ruff → mypy → alembic upgrade → pytest
2. **web** job — eslint → tsc → vite build
3. **docker** job — smoke-builds both production Docker images (runs only on push, after api+web pass)
