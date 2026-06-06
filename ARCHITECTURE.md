# MCP Gateway — Architecture, Design & Working

**Version:** 0.1.0 | **Platform:** Docker Compose | **Stack:** Python 3.12 + React 18 + PostgreSQL + Redis

---

## 1. What Is MCP Gateway?

MCP Gateway is a **secure agentic AI orchestration platform** built on the Model Context Protocol (MCP). It allows users to describe tasks in natural language; an AI agent autonomously plans, executes, and reviews a sequence of tool calls across multiple real-world services (GitHub, Jira, Slack, Google Drive, a vector knowledge base) — then delivers a structured answer.

**Key capabilities:**
- Natural language task orchestration via LangGraph + GPT-4o
- Live integration with 5 external services (50+ tools total)
- Role-based access control enforced at both UI and API level
- Tamper-evident audit log with SHA-256 hash chain
- Email OTP authentication (Resend API)
- Semantic knowledge base with persistent pgvector storage
- Real-time workflow event streaming via WebSocket + Redis pub/sub

---

## 2. System Architecture

### 2.1 High-Level Components

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Browser Client                             │
│  React 18 + Vite + TanStack Query + Tailwind                       │
│  Auth: JWT stored in localStorage, sent as Bearer token            │
└────────────────────────────────┬────────────────────────────────────┘
                                 │  HTTP / WebSocket
                                 │  /api/* proxy (Vite dev)
┌────────────────────────────────▼────────────────────────────────────┐
│                       FastAPI Backend (:8000)                       │
│  ┌──────────────┐ ┌─────────────┐ ┌──────────────┐ ┌────────────┐ │
│  │ Auth Router  │ │  Registry   │ │  Workflows   │ │ Audit Log  │ │
│  │ /auth/*      │ │ /registry/* │ │ /workflows/* │ │ /audit-*   │ │
│  └──────────────┘ └─────────────┘ └──────┬───────┘ └────────────┘ │
│                                           │                         │
│  ┌─────────────────────────────────────── ▼────────────────────┐   │
│  │              LangGraph Orchestrator (gpt-4o)                │   │
│  │  planner → executor → reviewer                              │   │
│  │              ↕ parallel wave execution                      │   │
│  └─────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    MCP Adapter Layer                         │  │
│  │  GitHub(14) │ Slack(10) │ Jira(10) │ GDrive(5) │ KB(1)     │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────┐   ┌──────────────┐   ┌─────────────────────┐ │
│  │  OPA :8181      │   │  Redis :6379 │   │  PostgreSQL :5432   │ │
│  │  RBAC Policies  │   │  OTP / Cache │   │  + pgvector         │ │
│  └─────────────────┘   └──────────────┘   └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                                 │  HTTP
┌────────────────────────────────▼────────────────────────────────────┐
│              KB RAG Service (:8001) — apps/kb/                     │
│  sentence-transformers + pgvector + OpenAI gpt-4o-mini             │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Docker Compose Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `api` | `mcpgateway-api` | 8000 | FastAPI backend |
| `web` | `mcpgateway-web` | 5173 | React frontend (Vite dev) |
| `kb` | `mcpgateway-kb` | 8001 | Knowledge Base RAG service |
| `postgres` | `pgvector/pgvector:pg16` | 5432 | Primary database + vector store |
| `redis` | `redis:7-alpine` | 6379 | OTP TTL, cache, pub/sub |
| `opa` | `openpolicyagent/opa:latest` | 8181 | RBAC policy engine |

---

## 3. Authentication & Authorization

### 3.1 Email OTP Flow

```
User                  Frontend              API                  Redis     Resend
 │                       │                   │                     │         │
 │  Enter email          │                   │                     │         │
 ├──────────────────────►│                   │                     │         │
 │                       │  POST /auth/request-otp                 │         │
 │                       ├──────────────────►│                     │         │
 │                       │                   │  Check users table  │         │
 │                       │                   │  Generate OTP       │         │
 │                       │                   │  HMAC-SHA256 code   │         │
 │                       │                   ├────────────────────►│         │
 │                       │                   │  SETEX otp:{email} 300s       │
 │                       │                   │                     │         │
 │                       │                   ├─────────────────────┼────────►│
 │                       │                   │                     │  Send email
 │  Check email          │                   │                     │         │
 ├──────────────────────►│                   │                     │         │
 │  Enter 6-digit code   │                   │                     │         │
 │                       │  POST /auth/verify-otp                  │         │
 │                       ├──────────────────►│                     │         │
 │                       │                   │  GET otp:{email}   ◄┤         │
 │                       │                   │  HMAC compare       │         │
 │                       │                   │  DEL otp:{email}   ►│         │
 │                       │                   │  Create JWT (24h)   │         │
 │                       │◄──────────────────┤  {token, user}      │         │
 │                       │  Store in localStorage                  │         │
 │  Redirect /workflows  │                   │                     │         │
```

**JWT Payload:**
```json
{
  "sub": "uuid",
  "email": "user@example.com",
  "name": "Full Name",
  "role": "admin | engineer | viewer",
  "iat": 1780000000,
  "exp": 1780086400
}
```

### 3.2 Role-Based Access Control

| Action | admin | engineer | viewer |
|--------|-------|----------|--------|
| View workflows | ✓ | ✓ | ✓ |
| Create workflows | ✓ | ✓ | ✗ |
| Approve checkpoints | ✓ | ✓ | ✗ |
| View audit log | ✓ | ✓ | ✓ |
| Registry CRUD | ✓ | ✗ (UI hidden) | ✗ |
| Write tool invocations | ✓ | ✓ (with approval gate) | ✗ |

Enforcement is dual-layer:
1. **UI layer** — Registry route not rendered for non-admins; Sidebar hides Registry link
2. **OPA layer** — Rego policies evaluate `{actor_role, tool_name, permission}` at every tool invocation

### 3.3 Middleware Priority

Every request to the API (except `/auth/*`, `/health`, `/docs`) passes through `ApiKeyMiddleware`:
1. `Authorization: Bearer <jwt>` → decode → `request.state.actor = user.name`, `actor_role = user.role`
2. `X-API-Key: <key>` → lookup in settings → set actor + role
3. Neither → anonymous (`actor = None`)

Existing API key auth (`X-API-Key`) coexists with JWT auth for backward compatibility with curl/scripts.

---

## 4. Agent Orchestration

### 4.1 Pre-flight Analysis (Before Workflow Creation)

Before creating a workflow, the frontend calls `POST /workflows/analyze`:

```
User submits task
       │
       ▼
POST /workflows/analyze
       │
       ├─ Pattern matching on task text
       │    "jira" + "create/ticket" → needs project_key, priority, assignee
       │    "slack" + "post/send" + no #channel → needs channel
       │
       ├─ Live option fetching (direct adapter calls)
       │    Jira: GET /project/search → project list
       │    Jira: GET /user/assignable/search?project=KEY → member list
       │    Slack: list_channels → channel list
       │
       └─ Returns {needs_clarification: bool, questions: [...]}
              │
              ▼
       ClarificationCard (frontend)
              │
       User selects project, priority, assignee
              │
              ▼
       enrichTask() → "...Use Jira project key MGORCH, set priority to High, assign to accountId=xxx"
              │
              ▼
       POST /workflows (with enriched task)
```

### 4.2 LangGraph State Machine

```
          ┌─────────────┐
START ───►│   planner   │
          └──────┬──────┘
                 │ produces JSON plan [{step_order, server, tool, args}]
          ┌──────▼──────┐
          │  executor   │◄──────────────────────────┐
          └──────┬──────┘                           │
                 │ runs steps (parallel waves)       │
          ┌──────▼──────┐                           │
          │  reviewer   │ insufficient + budget ─────┘
          └──────┬──────┘
                 │ sufficient
                END
```

**Planner (gpt-4o, temperature=0):**
- Receives full tool manifest (all active server capabilities with input schemas)
- Outputs a JSON plan with step_order, server_name, tool_name, arguments, depends_on
- Rules enforced in system prompt: default repos/projects, assignee in create_issue, `{{step_results}}` for Slack posts

**Executor (parallel wave execution):**
- `_build_execution_waves()` groups steps by `depends_on` DAG
- Steps with no unresolved dependencies run in parallel via `asyncio.gather`
- Each parallel step gets its own `AsyncSessionLocal()` session to avoid asyncpg deadlocks
- Step results committed per-step; workflow DB state updated in real-time

**Reviewer (gpt-4o, temperature=0):**
- Receives human-readable step results summary (not raw JSON)
- Judges sufficiency; synthesises markdown final answer
- `MAX_REPLANS = 0` — no replanning loops (improves latency)

**Approval Checkpoint:**
- Write-permission tools trigger `AWAITING_APPROVAL` status
- Frontend shows Approve/Reject panel
- Background task waits on Redis key `workflow:{id}:approval`
- Approved: execution continues; Rejected: step skipped/cancelled

### 4.3 WebSocket Event Streaming

```
Orchestrator                 Redis                  Browser WebSocket
     │                         │                         │
     │  r.publish(channel, event)                        │
     ├────────────────────────►│                         │
     │                         │  subscribe(channel)     │
     │                         │◄────────────────────────┤
     │                         │  forward event          │
     │                         ├────────────────────────►│
     │                         │                         │  Update UI
```

Events: `status_change`, `plan_ready`, `step_started`, `step_completed`, `step_failed`, `step_denied`, `checkpoint_reached`, `checkpoint_approved`, `review_started`, `workflow_completed`, `workflow_failed`

---

## 5. MCP Adapter Layer

### 5.1 Architecture Pattern

```python
BaseAdapter (ABC)
    │
    ├── invoke_tool(server, tool_name, arguments, db, actor)
    │       ├── resolve_credentials(server) → {"Authorization": "Bearer ..."}
    │       ├── _execute_tool(server, tool_name, arguments, headers)
    │       ├── write_audit_log(db, action, actor, result/error, latency_ms)
    │       └── _update_latency(db, server_id, tool_name, latency_ms)
    │
    └── _get_tool_definitions() → [tool schema list]
```

`resolve_credentials()`: reads `auth_config.token_env_var` from the server DB row → reads the value from `os.environ` → returns HTTP Authorization header. Checked first against `token_env_var`, not `auth_type` (which defaults to NONE).

### 5.2 Registered Adapters & Tools

| Adapter | Tools | Auth Method |
|---------|-------|-------------|
| GitHub (`github-mcp`) | list_repos, get/list_prs, get/list_issues, get_file_contents, list_commits, get_commit, search_code, create_issue, close_issue, comment_on_pr, create_branch, get_repo_stats | Bearer token |
| Slack (`slack-mcp`) | list_channels, get_channel_history, post_message, get_user_info, search_messages, update_message, add_reaction, get_thread_replies, list_users, get_channel_info | Bearer token |
| Jira (`jira-mcp`) | get_issue, search_issues, list_projects, create_issue, update_issue, transition_issue, add_comment, get_comments, assign_issue, get_sprint_issues | Basic Auth |
| Google Drive (`gdrive-mcp`) | list_files, get_file_metadata, download_file, search_files, list_shared_drives | Bearer token |
| Knowledge Base (`kb-mcp`) | query | None (internal) |

### 5.3 Error Handling

| Error Type | HTTP Code | Meaning |
|------------|-----------|---------|
| `AdapterNotFoundError` | 503 | No adapter for this `adapter_type` |
| `CredentialResolutionError` | 503 | `token_env_var` not set in environment |
| `AdapterError` (with status) | 502 (or upstream code) | Upstream API call failed |
| Tool not in `server_capabilities` | 422 | Tool not registered |
| Server not found | 404 | Unknown `server_id` |

---

## 6. Knowledge Base (RAG Pipeline)

### 6.1 Pipeline

```
Document ingestion:
  text → all-MiniLM-L6-v2 → 384-dim float32 vector → psycopg2 INSERT → kb_documents table

Query:
  question → encode → vector
       │
       └─ SELECT ... 1 - (embedding <=> $query_vec) AS score
          FROM kb_documents ORDER BY embedding <=> $query_vec LIMIT 5
       │
       └─ top-k chunks → GPT-4o-mini → {answer, sources, question}
```

### 6.2 Storage

- **Table:** `kb_documents` (id UUID, title TEXT, content TEXT, metadata JSONB, embedding vector(384), created_at)
- **Index:** pgvector cosine similarity (`<=>` operator)
- **Connection:** psycopg2 (synchronous, psycopg2-binary) — NOT asyncpg
- **Model:** `sentence-transformers/all-MiniLM-L6-v2` (22 MB, CPU, pre-downloaded at Docker build time)

---

## 7. Audit Log & Security

### 7.1 Tamper-Evident Hash Chain

Every `AuditLog` entry is chained:
```
entry_hash = SHA-256(id + action + actor + tool_name + timestamp + prev_hash)
```

Inserting a new entry reads the last `entry_hash` from the table and includes it as `prev_hash`. Tampering with any entry breaks the chain — detectable via `GET /audit-logs/stats` → `chain_valid: false`.

### 7.2 OPA Policy Engine

Policies (Rego) in `opa/policies/`. Evaluated before every tool invocation:
- Input: `{actor, actor_role, server_name, tool_name, required_permission}`
- Output: `allow: true/false` with reason
- Write operations (`required_permission = "write"`) from `engineer` role → `AWAITING_APPROVAL` instead of immediate execution

### 7.3 Audit Log Schema

```
audit_logs
  id UUID
  action: tool_call | tool_blocked | workflow_started | workflow_completed | server_registered | ...
  actor: string (user name from JWT / API key)
  server_name: string
  tool_name: string
  allowed: bool
  request_payload: JSONB
  response_payload: JSONB  ← {result: ...} on success, {error: "..."} on failure
  policy_decision: JSONB   ← OPA decision details
  latency_ms: int
  entry_hash: string (SHA-256)
  prev_hash: string (previous entry's hash)
  created_at: timestamptz
```

---

## 8. Frontend Architecture

### 8.1 Page Structure

```
/login              → LoginPage (public, no auth required)
/workflows          → WorkflowsPage (home, full-height chat UI)
/dashboard          → DashboardPage (health stats, adapter status)
/registry           → RegistryPage (admin only)
/audit              → AuditLogPage (filterable, clickable rows)
```

### 8.2 Chat UI (WorkflowsPage)

The workflow page implements a Claude-like conversation interface:

```
┌─────────────────────────────────────────────────┐
│ [User message]                                  │
│                                                 │
│ [AI response]                                   │
│   ✓ Step 1: list_commits  github-mcp   477ms   │
│   ✓ Step 2: create_issue  jira-mcp     1175ms  │
│   ● Answer (markdown rendered)                  │
│                                                 │
│ [User message 2] ← follow-up in same thread    │
│ [AI response 2]                                 │
│                                                 │
├─────────────────────────────────────────────────┤
│  [textarea                              ↑ send] │
└─────────────────────────────────────────────────┘
```

**Multi-turn conversation:** All workflow IDs in a thread are encoded in the URL as `?wf=id1,id2,id3`. Refreshing preserves the full thread. Clicking a sidebar history item resets to a single-workflow view.

**Pre-flight clarification:** `useAnalyzeWorkflow` is called on submit. If `needs_clarification: true`, a `ClarificationCard` replaces the empty state — users pick from live-fetched options (project chips, priority chips, member searchable dropdown) before the workflow is created.

### 8.3 State Management

- **Server state:** TanStack Query (React Query) — workflows poll every 5s, stops on terminal status
- **Auth state:** `AuthContext` (React Context) — user, token, isAdmin; persisted via localStorage
- **UI state:** local component state
- **URL state:** `useSearchParams` for selected workflow IDs; `useLocation` for navigation intent

### 8.4 Hooks

| Hook | Purpose |
|------|---------|
| `useWorkflows(limit)` | Poll workflow list every 5s |
| `useWorkflow(id)` | Poll single workflow; stops on terminal |
| `useCreateWorkflow()` | POST /workflows mutation |
| `useAnalyzeWorkflow()` | POST /workflows/analyze mutation |
| `useWorkflowStream(id)` | WebSocket connection, returns events[] |
| `useApproveCheckpoint()` | POST /workflows/{id}/approve |
| `useRejectCheckpoint()` | POST /workflows/{id}/reject |
| `useAuditLogs(params)` | Filtered audit log list, refetch 10s |
| `useAuditStats()` | Stats including chain_valid, refetch 30s |
| `useHealthCheck()` | GET /health |
| `useRegistry()` | Registry server list |

---

## 9. Database Schema

```sql
-- Users (auth)
users (id UUID PK, name TEXT, email TEXT UNIQUE, role TEXT, is_active BOOL, created_at TIMESTAMPTZ)

-- MCP Registry
mcp_servers (id UUID PK, name TEXT UNIQUE, display_name TEXT, base_url TEXT,
             auth_type TEXT, auth_config JSONB, metadata JSONB, health_status TEXT,
             is_active BOOL, created_at, updated_at)

server_capabilities (id UUID PK, server_id FK, tool_name TEXT, description TEXT,
                     input_schema JSONB, output_schema JSONB, required_permission TEXT,
                     avg_latency_ms FLOAT, is_active BOOL)

-- Workflow execution
workflows (id UUID PK, task TEXT, initiated_by TEXT, status TEXT, plan JSONB,
           result JSONB, error_message TEXT, total_tokens_used INT,
           created_at, updated_at, completed_at)

workflow_steps (id UUID PK, workflow_id FK, step_order INT, agent_role TEXT,
                server_name TEXT, tool_name TEXT, status TEXT,
                input_payload JSONB, output_payload JSONB, error_message TEXT,
                tokens_used INT, latency_ms INT, created_at, completed_at)

-- Audit
audit_logs (id UUID PK, workflow_id FK nullable, action TEXT, actor TEXT,
            server_name TEXT, tool_name TEXT, allowed BOOL,
            request_payload JSONB, response_payload JSONB, policy_decision JSONB,
            latency_ms INT, entry_hash TEXT, prev_hash TEXT, created_at TIMESTAMPTZ)

-- Knowledge Base (managed by KB service, not Alembic)
kb_documents (id UUID PK, title TEXT, content TEXT NOT NULL, metadata JSONB,
              embedding vector(384), created_at TIMESTAMPTZ)
```

---

## 10. API Reference Summary

### Auth
```
POST /auth/request-otp    {email}                → {message} [+ dev_code in dev mode]
POST /auth/verify-otp     {email, code}           → {token, user}
GET  /auth/me             Bearer token            → {id, name, email, role}
```

### Workflows
```
POST /workflows/analyze   {task, actor}           → {needs_clarification, questions[]}
POST /workflows           {task, actor}           → Workflow (201, starts async)
GET  /workflows           ?limit&offset           → {total, items[]}
GET  /workflows/{id}      —                       → Workflow + steps
POST /workflows/{id}/approve                      → {approved}
POST /workflows/{id}/reject                       → {rejected}
WS   /workflows/{id}/stream                       → stream of StreamEvent JSON
```

### Registry
```
POST   /registry/servers                          → Server (201)
GET    /registry/servers  ?active_only&health_status → {total, items[]}
GET    /registry/servers/{id}                     → Server + capabilities
PATCH  /registry/servers/{id}                     → Server (partial update)
DELETE /registry/servers/{id}                     → {deleted}
PUT    /registry/servers/{id}/capabilities        → capabilities[]
GET    /registry/tools    ?name&permission        → tools[]
```

### Tools
```
POST /tools/invoke  {server_id, tool_name, arguments, actor?} → ToolResult
```

### Audit
```
GET /audit-logs   ?actor&server&tool&action&allowed&from_ts&to_ts&limit&offset
                                                  → {total, items[]}
GET /audit-logs/stats                             → {total, blocked_today, tool_calls_today, chain_valid, last_entry_hash}
GET /audit-logs/export                            → CSV download
```

### Health
```
GET /health   → {status, version, environment, uptime_seconds, dependencies: {postgres, redis}}
```

---

## 11. Configuration Reference

```bash
# Database
DATABASE_URL=postgresql+asyncpg://mcp_user:mcp_password@postgres:5432/mcp_gateway

# Cache / Pub-Sub / OTP
REDIS_URL=redis://redis:6379/0

# Security
SECRET_KEY=<32-byte random hex>    # Signs JWTs + HMACs OTPs
OPA_URL=http://opa:8181

# LLM
OPENAI_API_KEY=sk-proj-...         # GPT-4o (orchestrator) + GPT-4o-mini (KB)

# Email
RESEND_API_KEY=re_...              # OTP delivery via Resend API

# Service Tokens (stored by reference, never raw in DB)
GITHUB_TOKEN=ghp_...
SLACK_BOT_TOKEN=xoxb-...
JIRA_API_TOKEN=ATATT3x...
JIRA_USER_EMAIL=user@example.com
JIRA_URL=https://workspace.atlassian.net
GOOGLE_ACCESS_TOKEN=ya29....

# Role mappings for API key / anonymous access
ACTOR_ROLES={"abhishek": "admin", "user": "engineer", ...}
API_KEYS={"sk-admin-demo": {"actor": "abhishek", "role": "admin"}, ...}

# App
ENVIRONMENT=development            # development | test | production
CORS_ORIGINS=["http://localhost:5173"]   # must be JSON array
```

---

## 12. Data Flow: Complete Workflow Execution

```
1. User enters task in browser input bar
   └─ Frontend calls POST /workflows/analyze
   └─ If clarification needed → ClarificationCard shown
   └─ User fills project/priority/assignee
   └─ enrichTask() builds complete task string

2. POST /workflows {task, actor}
   └─ Workflow record created (status=PENDING), DB committed
   └─ asyncio.create_task(_run_workflow_background) — returns 201 immediately

3. Background task starts (own DB session)
   └─ status → PLANNING
   └─ Planner calls GPT-4o with full tool manifest
   └─ GPT-4o returns JSON plan [{step_order, server, tool, args, depends_on}]
   └─ WorkflowStep rows created, status → RUNNING
   └─ Redis publish: plan_ready event

4. Executor runs waves
   └─ Wave 1 (no dependencies): steps run in parallel
   └─ Each step:
       a. OPA policy check → allowed or AWAITING_APPROVAL
       b. resolve_credentials(server) → Authorization header
       c. adapter._execute_tool(server, tool, args, headers)
       d. Write AuditLog entry (response_payload stores result or error)
       e. Update WorkflowStep (status=COMPLETED/FAILED, latency_ms)
       f. Redis publish: step_completed / step_failed event
   └─ Wave 2+ (depends on wave 1): same pattern

5. Reviewer calls GPT-4o with human-readable step results summary
   └─ Sufficient → COMPLETED, final_answer written to workflows.result
   └─ Insufficient → FAILED (MAX_REPLANS=0)
   └─ Redis publish: workflow_completed / workflow_failed

6. Frontend (WebSocket)
   └─ Receives each event, updates step status UI in real-time
   └─ On workflow_completed: displays markdown final answer
   └─ URL updated to include all conversation workflow IDs
```

---

## 13. Security Considerations

1. **No tokens stored in DB** — credentials resolver reads `token_env_var` → looks up `os.environ`. The DB only stores the variable name.
2. **OTPs are HMAC-hashed** — Redis stores `HMAC-SHA256(code, SECRET_KEY)`, not the raw code. Timing-safe comparison via `hmac.compare_digest`.
3. **One-time OTPs** — Redis key deleted immediately after successful verification.
4. **JWT expiry** — 24-hour expiry; 401 response triggers automatic logout + redirect.
5. **Audit chain** — SHA-256 hash chain detects tampering with any historical audit entry.
6. **Write operations require approval** — engineer role cannot execute write tools without explicit human approval.
7. **CORS** — restricted to `localhost:5173` and `localhost:3000` by default.
8. **SQL injection** — SQLAlchemy ORM with parameterized queries throughout; no raw string interpolation in SQL.
