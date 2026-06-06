# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCP Gateway is a secure agentic AI orchestration platform with email-based authentication and role-based access control. A Turborepo monorepo with three apps:
- `apps/api` — FastAPI backend (Python 3.12)
- `apps/web` — React 18 frontend (TypeScript)
- `apps/kb` — Knowledge Base RAG service (FastAPI + sentence-transformers + pgvector, Python 3.12)

**Three registered users** (seeded in DB migration 0003):
- `abhischavan18@gmail.com` — role `admin` (full access including Registry)
- `arshadvani3@gmail.com` — role `engineer`
- `shubhamsharma33@gmail.com` — role `engineer`

## Development Commands

### Start everything (recommended)
```bash
cp .env.example .env   # first time only — fill in API tokens
docker compose up --build
# API:  http://localhost:8000  (docs at /docs)
# KB:   http://localhost:8001  (docs at /docs)
# Web:  http://localhost:5173
```

### Backend (`apps/api/`)
All commands run from `apps/api/`.

```bash
pip install -e ".[dev]"
uvicorn mcp_gateway.main:app --reload --reload-dir src

ruff check src tests && ruff format src tests
mypy src

pytest
pytest tests/test_health.py -v
pytest --cov=mcp_gateway --cov-report=term-missing

alembic upgrade head
alembic revision --autogenerate -m "description"
alembic downgrade -1
```

### Frontend (`apps/web/`)
```bash
npm install          # from monorepo root, not apps/web/
npm run dev
npm run build
npm run typecheck
npm run lint
```

## Architecture

### Request flow
```
Browser → React (Vite :5173)
             └─ /api/* proxy → FastAPI (:8000)
                                  ├─ ApiKeyMiddleware (JWT Bearer / X-API-Key)
                                  ├─ Auth Router (/auth/*)
                                  ├─ Security Gateway (OPA :8181)
                                  ├─ MCP Registry (/registry/*)
                                  ├─ Tool Invoker (/tools/invoke)
                                  ├─ Pre-flight Analyzer (/workflows/analyze)
                                  └─ Agent Orchestrator (/workflows/*)
                                        └─ MCP Adapters
                                              ├─ GitHub (14 tools)
                                              ├─ Slack (10 tools)
                                              ├─ Jira (10 tools)
                                              ├─ Google Drive (5 tools)
                                              └─ Knowledge Base (1 tool) ← apps/kb/ (:8001)
```

### Backend structure (`apps/api/src/mcp_gateway/`)

- **`config.py`** — `Settings` (Pydantic Settings) read from `.env`. Includes `resend_api_key`, `openai_api_key`, `secret_key`. Import `settings` everywhere.
- **`database.py`** — async SQLAlchemy engine + `AsyncSessionLocal`. Use `get_db` as FastAPI `Depends`.
- **`main.py`** — `create_app()` factory. Registers routers: `auth`, `health`, `registry`, `tools`, `workflows`, `audit`.
- **`models/`** — ORM models. All imported in `models/__init__.py` for Alembic autogenerate.
- **`routers/`** — `auth.py`, `health.py`, `registry.py`, `tools.py`, `workflows.py`, `audit.py`.
- **`schemas/`** — Pydantic request/response models. `AuditLogResponse` includes `response_payload` (where adapter errors are stored).
- **`services/`** — `registry.py`, `cache.py`, `health_scheduler.py`, `orchestrator.py`, `adapters/`.
- **`middleware/auth.py`** — `ApiKeyMiddleware`: resolves identity from JWT Bearer token OR `X-API-Key` header. Public paths (`/auth/*`, `/health`, `/docs`) bypass auth entirely.

### Database schema (PostgreSQL + pgvector)

Six tables, all using UUID PKs:
- `users` — registered users with name, email, role, is_active (migration 0003)
- `mcp_servers` + `server_capabilities` — MCP Registry
- `workflows` + `workflow_steps` — execution tracking
- `audit_logs` — append-only; every tool call and security decision; has `entry_hash`/`prev_hash` SHA-256 chain
- `kb_documents` — vector embeddings via pgvector (created at KB service startup, not via Alembic)

Migrations: `0001_initial_schema.py`, `0002_audit_hash_chain.py`, `0003_users.py`.
The postgres image is `pgvector/pgvector:pg16` (not `postgres:16-alpine`) to support the vector extension.

### Frontend structure (`apps/web/src/`)

- **`main.tsx`** — mounts React. Sets `axios.defaults.headers.common["Authorization"]` from `localStorage` on load. Interceptor clears token + redirects to `/login` on 401.
- **`App.tsx`** — `RequireAuth` wrapper redirects unauthenticated users to `/login`. Registry route only rendered for `user.role === "admin"`.
- **`contexts/AuthContext.tsx`** — `AuthProvider` stores `user`, `token`, `isAdmin`. `login()` sets localStorage + axios header. `logout()` clears both. Validates stored token against `GET /auth/me` on load.
- **`components/layout/Layout.tsx`** — no topbar. Workflow page gets full-height layout; other pages get `overflow-y-auto p-8` wrapper.
- **`components/layout/Sidebar.tsx`** — collapsible (`w-64` ↔ `w-14`). Shows workflow history, search box, nav links (Registry hidden for non-admins), user name/role/logout in footer.
- **`pages/LoginPage.tsx`** — two-step: email → OTP. Shows `dev_code` from API in yellow card when email delivery fails.
- **`pages/WorkflowsPage.tsx`** — full-height chat UI. Input bar always at bottom. Multi-turn conversation: follow-up messages append to same thread; all IDs encoded in URL as `?wf=id1,id2,id3`. Pre-flight analysis via `useAnalyzeWorkflow` shows `ClarificationCard` before workflow creation.
- **`pages/AuditLogPage.tsx`** — clickable rows expand to show full `response_payload.error`, `policy_decision`, entry hash.

## Environment

Key `.env` variables:
- `DATABASE_URL` — asyncpg URL; Docker Compose overrides to use `postgres` service name
- `REDIS_URL` — OTP storage (TTL), pub/sub event streaming, registry cache
- `SECRET_KEY` — signs JWT tokens; also used to HMAC OTP codes
- `OPENAI_API_KEY` — required by orchestrator (gpt-4o) and KB service (gpt-4o-mini)
- `RESEND_API_KEY` — sends OTP emails via Resend API (`onboarding@resend.dev` sender)
- `GITHUB_TOKEN` — stored as `auth_config.token_env_var` on the `github-mcp` server row
- `SLACK_BOT_TOKEN` — same pattern for Slack
- `JIRA_API_TOKEN` + `JIRA_USER_EMAIL` — Jira adapter uses Basic Auth `base64(email:token)`
- `JIRA_URL` — base URL for Jira instance (e.g. `https://yourworkspace.atlassian.net`)
- `GOOGLE_ACCESS_TOKEN` — same pattern for Google Drive
- `ACTOR_ROLES` — JSON map of actor name → role (for API key / anonymous access)
- `API_KEYS` — JSON map of key → `{actor, role}` for programmatic/curl access
- `OPA_URL` — OPA policy engine (Docker: `http://opa:8181`)

## Authentication System

### Flow
1. `POST /auth/request-otp` — checks email in `users` table, generates 6-digit code, stores HMAC-SHA256 of code in Redis (`otp:{email}`, 5-min TTL), sends via Resend API
2. `POST /auth/verify-otp` — retrieves hash from Redis, verifies with `hmac.compare_digest`, deletes key (one-time use), returns JWT + user dict
3. JWT payload: `{sub: user_id, email, name, role, iat, exp (+24h)}`, signed with `SECRET_KEY` using HS256
4. `GET /auth/me` — validates JWT, returns current user (frontend calls on load)

### Middleware
`ApiKeyMiddleware` resolves identity in this priority order:
1. `Authorization: Bearer <jwt>` → decode JWT → set `request.state.actor` (user name) + `actor_role`
2. `X-API-Key: <key>` → look up in `settings.api_keys` → set actor + role
3. Neither → anonymous (actor = None)

All `/auth/*` paths bypass the middleware entirely via `_PUBLIC_PATHS`.

### Role-based access
- `admin` — full access including Registry mutations
- `engineer` — workflows, audit log, tool invocations (write tools need approval)
- `viewer` — read-only

Frontend enforces UI visibility (Registry hidden). Backend enforces via OPA policies at tool invocation time.

## Adapter Layer

Files in `services/adapters/`:

- **`base.py`** — `BaseAdapter` ABC. `invoke_tool()` handles timing, credential injection, `AuditLog` write (`db.flush()`), EMA latency update. Stores error in `response_payload: {"error": str(exc)}`. Subclasses implement `_execute_tool` and `_get_tool_definitions`.
- **`credentials.py`** — `resolve_credentials(server) → dict`. If `auth_config.token_env_var` is set, **always resolves it regardless of `auth_type`** (critical fix — `auth_type` defaults to `NONE` which previously returned `{}` silently). Never stores raw tokens in DB.
- **`github.py`** — 14 tools: `list_repos`, `get_pr`, `list_prs`, `get_issue`, `list_issues`, `get_file_contents`, `list_commits`, `get_commit`, `search_code`, `create_issue`, `close_issue`, `comment_on_pr`, `create_branch`, `get_repo_stats`. `_list_repos` uses `/users/{owner}/repos` when `owner` arg is set (not `/user/repos` which returns authenticated user's repos).
- **`slack.py`** — 10 tools: `list_channels`, `get_channel_history`, `post_message`, `get_user_info`, `search_messages`, `update_message`, `add_reaction`, `get_thread_replies`, `list_users`, `get_channel_info`. `_post_message` accepts `text`, `message`, `content`, or `summary` as the message key.
- **`jira.py`** — 10 tools: `get_issue`, `search_issues`, `list_projects`, `create_issue`, `update_issue`, `transition_issue`, `add_comment`, `get_comments`, `assign_issue`, `get_sprint_issues`. Uses Basic Auth `base64(JIRA_USER_EMAIL:JIRA_API_TOKEN)`. ADF responses extracted to plain text by `_extract_text()`. Search uses `/rest/api/3/search/jql` (not deprecated `/search`). `create_issue` accepts `assignee` arg (Jira accountId) directly — no separate `assign_issue` step needed.
- **`gdrive.py`** — 5 tools. `GDRIVE_API_BASE` hardcoded; `server.base_url` only used by health scheduler. Set `base_url` to `https://www.googleapis.com/discovery/v1/apis` so it shows healthy.
- **`kb.py`** — 1 tool: `query` (full RAG). The `search` tool is NOT registered as a capability — only `query` is exposed to the planner.
- **`registry.py`** — `get_adapter(server)`. Registry: `{github, slack, gdrive, kb, jira}`.

Tool invocation: `POST /tools/invoke` — body `{server_id, tool_name, arguments, actor?}`. Error codes: 404 (unknown server), 422 (unregistered tool), 503 (no adapter / missing credential), 502 (adapter HTTP error).

## Knowledge Base (apps/kb/)

**pgvector persistence** — documents stored in `kb_documents` table (PostgreSQL + pgvector extension). Embeddings: `vector(384)` column using `all-MiniLM-L6-v2` (384-dim). Generation: OpenAI `gpt-4o-mini`. No longer in-memory — documents survive container restarts.

Startup event `_init_db()` runs `CREATE EXTENSION IF NOT EXISTS vector` then `CREATE TABLE IF NOT EXISTS kb_documents` — idempotent, safe to run multiple times.

KB service connects to the same PostgreSQL instance as the API using a plain psycopg2 URL (`postgresql://` not `postgresql+asyncpg://`).

**Endpoints:**
- `GET /` + `GET /health` — returns `{status, documents}` (document count from DB)
- `POST /search` — semantic similarity search
- `POST /query` — full RAG: retrieve + generate
- `POST /documents` (201) — embed + store
- `GET /documents` — paginated list
- `DELETE /documents/{id}` — remove

## Agent Orchestrator

LangGraph state machine in `services/orchestrator.py`:
```
START → planner → executor → reviewer → END
                                │
                                └─(insufficient, MAX_REPLANS=0)──► planner
```

**LLM**: `gpt-4o` with `response_format={"type": "json_object"}`, `temperature=0` for planner and reviewer.

**Planner rules** (critical — read before modifying):
- GitHub `OWNER/REPO` format → split into `owner` and `repo` separately
- Default GitHub repo if unspecified: `owner=Abhishek231200`, `repo=mcp-gateway-backend`
- Default Jira project if unspecified: `project_key=MGORCH`
- When creating Jira issue with assignee: pass `assignee` to `create_issue` directly — do NOT add separate `assign_issue` step
- KB questions → use `query` tool with `question` key (not `search`)
- Slack posts with prior results → use `{{step_results}}` literal as text arg

**Parallel execution**: `_build_execution_waves()` groups steps by `depends_on`. Independent steps run via `asyncio.gather` with isolated `AsyncSessionLocal()` sessions per step.

**Pre-flight analysis** (`POST /workflows/analyze`):
- Called by frontend before `POST /workflows`
- Detects missing required params via pattern matching (no LLM)
- Fetches live options: Jira projects via `list_projects`, assignable users via `/user/assignable/search?project=KEY`, Slack channels via `list_channels`
- Returns `{needs_clarification, questions[]}` with `type: "select" | "searchable_select" | "text"`
- Frontend shows `ClarificationCard`; user fills answers; enriched task string passed to workflow

**WebSocket streaming**: Redis pub/sub channel `workflow:{id}:events`. Frontend `useWorkflowStream` hook opens WS, collects events, closes on terminal event type.

## Registry API

```
POST   /registry/servers              — register server
GET    /registry/servers              — paginated list (Redis-cached 60s)
GET    /registry/servers/{id}         — full server + capabilities
PATCH  /registry/servers/{id}         — partial update
DELETE /registry/servers/{id}         — hard delete
PUT    /registry/servers/{id}/capabilities — replace capability set
GET    /registry/tools                — cross-server tool search
```

Registering a server — `display_name` is required:
```json
{
  "name": "github-mcp",
  "display_name": "GitHub MCP",
  "base_url": "https://api.github.com",
  "metadata": {"adapter_type": "github"},
  "auth_config": {"token_env_var": "GITHUB_TOKEN"}
}
```

Live server registrations (do not modify):
- `github-mcp` — `base_url: https://api.github.com`
- `slack-mcp` — `base_url: https://slack.com`
- `jira-mcp` — `base_url: https://abhischavan18.atlassian.net`
- `kb-mcp` — `base_url: http://kb:8001`
- `gdrive-mcp` — `base_url: https://www.googleapis.com/discovery/v1/apis`

## Audit Log

`POST /audit-logs` — read only; `response_payload` (where adapter errors live) is included in `AuditLogResponse`. Frontend rows are clickable to expand full error detail. Server filter uses `ilike` (partial match). Auto-refreshes every 10s.

Stats endpoint `GET /audit-logs/stats` — returns total, blocked_today, tool_calls_today, chain_valid (SHA-256 hash chain integrity), last_entry_hash.

## Known Gotchas

- **`auth_type` defaults to `AuthType.NONE` → no credentials sent** — `resolve_credentials()` previously bailed early if `auth_type == NONE`, returning `{}`. ALL GitHub/Slack/Jira calls were unauthenticated (403 rate limit). Fixed: `credentials.py` now checks `token_env_var` first — if set, always resolves the token regardless of `auth_type`.

- **`response_payload` missing from audit schema** — The error message from failed tool calls is stored in `response_payload.error` on the ORM model but was not included in `AuditLogResponse`. Fixed: add `response_payload: dict | None` to the schema.

- **`POST /workflows/analyze` must be declared before `POST ""` in the router** — FastAPI matches routes in registration order. If the base `POST /workflows` is registered first, the `/analyze` path never matches. Always `include_router(auth.router)` first in `main.py` and declare `/analyze` before `""` in `workflows.py`.

- **JWT public paths need explicit allowlist in middleware** — `ApiKeyMiddleware` checks `request.url.path in _PUBLIC_PATHS` and also `startswith("/auth/")` before requiring auth. If you add new public endpoints, add them to `_PUBLIC_PATHS` in `middleware/auth.py`.

- **pgvector: `register_vector(conn)` must be called AFTER `CREATE EXTENSION IF NOT EXISTS vector` is committed** — Calling `register_vector` before the extension exists raises a type lookup error. In KB `_init_db()`: commit the `CREATE EXTENSION` statement first, then call `register_vector(conn)`.

- **pgvector image change requires volume reset** — Switching from `postgres:16-alpine` to `pgvector/pgvector:pg16` requires dropping the `postgres_data` volume (`docker compose down -v`) then running `alembic upgrade head` after restart. The KB `_init_db()` startup event handles subsequent runs idempotently.

- **Conversation IDs encoded in URL as comma-separated** — `?wf=id1,id2,id3`. Parse with `.split(",").filter(Boolean)`. Sidebar navigation always passes a single clean ID (`?wf=id`), which resets the conversation thread on page load.

- **`assign_issue` vs `create_issue` with assignee** — Planner previously added a separate `assign_issue` step causing `\n` in issue key URL (position 87 error). Fixed by: (1) adding `assignee` arg handling to `_create_issue`, (2) telling planner to use `create_issue` with `assignee` directly, (3) `.strip()` on all `issue_key`/`account_id` args in `_assign_issue`.

- **`docker compose restart` does not reload `env_file`** — Use `docker compose up -d --force-recreate <service>`. Adding `RESEND_API_KEY` to `.env` requires force-recreating the API container.

- **Resend free tier sender** — `onboarding@resend.dev` may only deliver to the account owner's verified email. For demo: `request-otp` returns `dev_code` in the response body when `ENVIRONMENT=development` and email delivery fails.

- **KB service uses psycopg2 (sync), not asyncpg** — `DATABASE_URL` for the KB service must be `postgresql://` (no `+asyncpg`). Docker Compose sets this separately for the `kb` service.

- **`CORS_ORIGINS` must be JSON in `.env`** — `CORS_ORIGINS=["http://localhost:5173","http://localhost:3000"]`. A comma-separated string causes `SettingsError` at startup.

- **Docker inter-container networking uses service names** — `http://api:8000`, `http://kb:8001`, `postgresql+asyncpg://...@postgres:5432/...`, `redis://redis:6379/0`.

- **Redis cache bust must use prefix scan** — use `cache_invalidate_prefix("registry:servers", "registry:tools")`. Exact-key delete is a no-op because cache keys include query params.

- **`db.flush()` in adapters, not `db.commit()`** — `invoke_tool` participates in the caller's request-scoped transaction.

- **`Enum(StrEnum)` uses member names, not values** — add `values_callable=lambda obj: [e.value for e in obj]` to every Enum column.

- **`ServerListResponse` items must include `capabilities`** — use `ServerWithCapabilities` not `ServerResponse` for list items.

- **Background orchestrator task must use its own DB session** — `asyncio.create_task(_run_workflow_background(...))` creates fresh `async with AsyncSessionLocal() as db`. Never share the request-scoped session.

- **`npm install` must be run from monorepo root** — not from `apps/web/`.

- **`pyproject.toml` build-backend must be `setuptools.build_meta`** — not `setuptools.backends.legacy:build`.

## CI

GitHub Actions (`.github/workflows/ci.yml`) on push/PR to `main`/`develop`:
1. **api** — Postgres + Redis services, ruff → mypy → alembic upgrade → pytest
2. **web** — eslint → tsc → vite build
3. **docker** — smoke-builds production images (push only, after api+web pass)
