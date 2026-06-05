"""Tests for the Workflows API (POST/GET /workflows) and orchestrator units.

Integration tests (registry_client fixture) require Postgres and are skipped
automatically when it is unreachable.  The orchestrator unit tests are fully
mocked and run without any DB or network dependency.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_gateway.models.workflow import StepStatus, WorkflowStatus


# ── REST endpoint integration tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_workflows_empty(registry_client: AsyncClient):
    """GET /workflows returns a valid paginated response (possibly empty)."""
    resp = await registry_client.get("/workflows")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_get_workflow_not_found(registry_client: AsyncClient):
    resp = await registry_client.get(f"/workflows/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_workflow_no_api_key(registry_client: AsyncClient):
    """Returns 503 when OPENAI_API_KEY is absent."""
    with patch("mcp_gateway.routers.workflows.settings") as mock_settings:
        mock_settings.openai_api_key = ""
        resp = await registry_client.post(
            "/workflows", json={"task": "List my GitHub repos", "actor": "test-user"}
        )
    assert resp.status_code == 503
    assert "OPENAI_API_KEY" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_workflow_success(registry_client: AsyncClient):
    """Creates a workflow record immediately and starts a background task."""
    with (
        patch("mcp_gateway.routers.workflows.settings") as mock_settings,
        patch("mcp_gateway.routers.workflows.asyncio.create_task") as mock_task,
    ):
        mock_settings.openai_api_key = "sk-test"
        mock_task.return_value = MagicMock()
        resp = await registry_client.post(
            "/workflows",
            json={"task": "List my GitHub repos", "actor": "test-user"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["task"] == "List my GitHub repos"
    assert data["initiated_by"] == "test-user"
    assert data["status"] == "pending"
    assert data["steps"] == []
    assert "id" in data
    mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_get_workflow_after_create(registry_client: AsyncClient):
    """Workflow created via POST is fetchable via GET /{id}."""
    with (
        patch("mcp_gateway.routers.workflows.settings") as mock_settings,
        patch("mcp_gateway.routers.workflows.asyncio.create_task") as mock_task,
    ):
        mock_settings.openai_api_key = "sk-test"
        mock_task.return_value = MagicMock()
        create_resp = await registry_client.post(
            "/workflows", json={"task": "Test task", "actor": "test"}
        )

    assert create_resp.status_code == 201
    wf_id = create_resp.json()["id"]

    get_resp = await registry_client.get(f"/workflows/{wf_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == wf_id
    assert get_resp.json()["task"] == "Test task"


@pytest.mark.asyncio
async def test_list_workflows_includes_created(registry_client: AsyncClient):
    """Workflow created via POST appears in GET /workflows list."""
    with (
        patch("mcp_gateway.routers.workflows.settings") as mock_settings,
        patch("mcp_gateway.routers.workflows.asyncio.create_task") as mock_task,
    ):
        mock_settings.openai_api_key = "sk-test"
        mock_task.return_value = MagicMock()
        create_resp = await registry_client.post(
            "/workflows", json={"task": "List task", "actor": "test"}
        )

    assert create_resp.status_code == 201
    wf_id = create_resp.json()["id"]

    list_resp = await registry_client.get("/workflows")
    assert list_resp.status_code == 200
    ids = [w["id"] for w in list_resp.json()["items"]]
    assert wf_id in ids


# ── Orchestrator unit tests ───────────────────────────────────────────────────
#
# These tests exercise the orchestrator node functions in isolation without
# hitting Postgres, Redis, or the OpenAI API.  All external calls are mocked.

def _make_db() -> AsyncSession:
    """Return a MagicMock that satisfies the async session interface."""
    db = MagicMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


def _make_workflow(workflow_id: str, status: WorkflowStatus = WorkflowStatus.PENDING) -> MagicMock:
    wf = MagicMock()
    wf.id = uuid.UUID(workflow_id)
    wf.status = status
    wf.plan = {}
    wf.total_tokens_used = 0
    wf.completed_at = None
    wf.error_message = None
    return wf


def _make_openai_response(content: str) -> MagicMock:
    """Build a mock that mimics openai.types.chat.ChatCompletion."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)
    return response


@pytest.mark.asyncio
async def test_planner_node_produces_plan():
    """Planner calls OpenAI and returns a validated plan list."""
    from mcp_gateway.services.orchestrator import WorkflowOrchestrator

    db = _make_db()
    workflow_id = str(uuid.uuid4())

    mock_wf = _make_workflow(workflow_id)
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none = MagicMock(return_value=mock_wf)
    db.execute = AsyncMock(return_value=scalar_mock)

    mock_response = _make_openai_response(
        '{"reasoning":"plan","steps":[{"step_order":1,"server_name":"github-mcp",'
        '"tool_name":"list_repos","arguments":{},"reasoning":"step1","depends_on":[]}]}'
    )

    orchestrator = WorkflowOrchestrator(db)

    state = {
        "workflow_id": workflow_id,
        "task": "List repos",
        "actor": "test-orchestrator",
        "available_tools": [
            {"server_name": "github-mcp", "tool_name": "list_repos",
             "description": "List repos", "input_schema": {}, "required_permission": "read"},
        ],
        "plan": [],
        "step_results": [],
        "replan_count": 0,
        "final_answer": None,
        "error": None,
    }

    with (
        patch("mcp_gateway.services.orchestrator.openai.AsyncOpenAI") as mock_cls,
        patch.object(orchestrator, "_publish_event", new_callable=AsyncMock),
    ):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await orchestrator._planner_node(state)

    assert "plan" in result
    assert len(result["plan"]) == 1
    assert result["plan"][0]["tool_name"] == "list_repos"


@pytest.mark.asyncio
async def test_planner_node_filters_invalid_tools():
    """Planner discards steps that reference tools not in the registry."""
    from mcp_gateway.services.orchestrator import WorkflowOrchestrator

    db = _make_db()
    workflow_id = str(uuid.uuid4())

    mock_wf = _make_workflow(workflow_id)
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none = MagicMock(return_value=mock_wf)
    db.execute = AsyncMock(return_value=scalar_mock)

    bad_plan = (
        '{"reasoning":"plan","steps":['
        '{"step_order":1,"server_name":"nonexistent","tool_name":"fake_tool","arguments":{},"reasoning":"x","depends_on":[]},'
        '{"step_order":2,"server_name":"github-mcp","tool_name":"list_repos","arguments":{},"reasoning":"y","depends_on":[]}'
        "]}"
    )
    mock_response = _make_openai_response(bad_plan)

    orchestrator = WorkflowOrchestrator(db)

    state = {
        "workflow_id": workflow_id,
        "task": "Test",
        "actor": "test-orchestrator",
        "available_tools": [
            {"server_name": "github-mcp", "tool_name": "list_repos",
             "description": "", "input_schema": {}, "required_permission": "read"},
        ],
        "plan": [],
        "step_results": [],
        "replan_count": 0,
        "final_answer": None,
        "error": None,
    }

    with (
        patch("mcp_gateway.services.orchestrator.openai.AsyncOpenAI") as mock_cls,
        patch.object(orchestrator, "_publish_event", new_callable=AsyncMock),
    ):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await orchestrator._planner_node(state)

    assert len(result["plan"]) == 1
    assert result["plan"][0]["server_name"] == "github-mcp"


@pytest.mark.asyncio
async def test_executor_node_calls_adapter():
    """Executor invokes the adapter for each plan step and captures results."""
    from mcp_gateway.services.orchestrator import WorkflowOrchestrator

    db = _make_db()
    workflow_id = str(uuid.uuid4())

    mock_wf = _make_workflow(workflow_id, WorkflowStatus.RUNNING)
    mock_step = MagicMock()
    mock_step.status = StepStatus.PENDING
    mock_step.output_payload = None
    mock_step.latency_ms = None
    mock_step.completed_at = None

    call_count = 0
    async def _execute(stmt: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        sm = MagicMock()
        sm.scalar_one_or_none = MagicMock(return_value=mock_wf if call_count == 1 else mock_step)
        return sm

    db.execute = _execute  # type: ignore[assignment]

    mock_server = MagicMock()
    mock_server.name = "github-mcp"

    mock_tool_result = {
        "result": [{"name": "repo1"}],
        "latency_ms": 123,
        "metadata": {"adapter_type": "github"},
    }

    orchestrator = WorkflowOrchestrator(db)

    state = {
        "workflow_id": workflow_id,
        "task": "List repos",
        "actor": "test-orchestrator",
        "available_tools": [
            {"server_name": "github-mcp", "tool_name": "list_repos",
             "description": "", "input_schema": {}, "required_permission": "read"},
        ],
        "plan": [{"step_order": 1, "server_name": "github-mcp", "tool_name": "list_repos",
                  "arguments": {}, "depends_on": []}],
        "step_results": [],
        "replan_count": 0,
        "final_answer": None,
        "error": None,
    }

    mock_adapter = AsyncMock()
    mock_adapter.invoke_tool = AsyncMock(return_value=mock_tool_result)

    mock_decision = MagicMock()
    mock_decision.allow = True

    mock_gw = AsyncMock()
    mock_gw.evaluate = AsyncMock(return_value=mock_decision)

    with (
        patch("mcp_gateway.services.orchestrator.get_server_by_name", new_callable=AsyncMock, return_value=mock_server),
        patch("mcp_gateway.services.orchestrator.get_adapter", return_value=mock_adapter),
        patch("mcp_gateway.services.orchestrator.get_security_gateway", return_value=mock_gw),
        patch.object(orchestrator, "_update_workflow_status", new_callable=AsyncMock),
        patch.object(orchestrator, "_publish_event", new_callable=AsyncMock),
    ):
        result = await orchestrator._executor_node(state)

    assert "step_results" in result
    assert len(result["step_results"]) == 1
    sr = result["step_results"][0]
    assert sr["tool_name"] == "list_repos"
    assert sr["error"] is None
    assert sr["latency_ms"] == 123


@pytest.mark.asyncio
async def test_executor_node_captures_step_failure():
    """Executor records an error result when the adapter raises AdapterError."""
    from mcp_gateway.services.adapters.base import AdapterError
    from mcp_gateway.services.orchestrator import WorkflowOrchestrator

    db = _make_db()
    workflow_id = str(uuid.uuid4())

    mock_wf = _make_workflow(workflow_id, WorkflowStatus.RUNNING)
    mock_step = MagicMock()
    mock_step.status = StepStatus.PENDING
    mock_step.error_message = None
    mock_step.latency_ms = None
    mock_step.completed_at = None

    call_count = 0
    async def _execute(stmt: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        sm = MagicMock()
        sm.scalar_one_or_none = MagicMock(return_value=mock_wf if call_count == 1 else mock_step)
        return sm

    db.execute = _execute  # type: ignore[assignment]

    orchestrator = WorkflowOrchestrator(db)

    state = {
        "workflow_id": workflow_id,
        "task": "Test",
        "actor": "test-orchestrator",
        "available_tools": [
            {"server_name": "github-mcp", "tool_name": "list_repos",
             "description": "", "input_schema": {}, "required_permission": "read"},
        ],
        "plan": [{"step_order": 1, "server_name": "github-mcp", "tool_name": "list_repos",
                  "arguments": {}, "depends_on": []}],
        "step_results": [],
        "replan_count": 0,
        "final_answer": None,
        "error": None,
    }

    mock_server = MagicMock()
    mock_adapter = AsyncMock()
    mock_adapter.invoke_tool = AsyncMock(
        side_effect=AdapterError("GitHub API returned 403", status_code=403)
    )

    mock_decision = MagicMock()
    mock_decision.allow = True

    mock_gw = AsyncMock()
    mock_gw.evaluate = AsyncMock(return_value=mock_decision)

    with (
        patch("mcp_gateway.services.orchestrator.get_server_by_name", new_callable=AsyncMock, return_value=mock_server),
        patch("mcp_gateway.services.orchestrator.get_adapter", return_value=mock_adapter),
        patch("mcp_gateway.services.orchestrator.get_security_gateway", return_value=mock_gw),
        patch.object(orchestrator, "_update_workflow_status", new_callable=AsyncMock),
        patch.object(orchestrator, "_publish_event", new_callable=AsyncMock),
    ):
        result = await orchestrator._executor_node(state)

    assert len(result["step_results"]) == 1
    assert result["step_results"][0]["error"] is not None
    assert "403" in result["step_results"][0]["error"]


@pytest.mark.asyncio
async def test_reviewer_node_marks_complete_on_success():
    """Reviewer sets final_answer when OpenAI says results are sufficient."""
    from mcp_gateway.services.orchestrator import WorkflowOrchestrator

    db = _make_db()
    workflow_id = str(uuid.uuid4())

    mock_wf = _make_workflow(workflow_id, WorkflowStatus.RUNNING)
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none = MagicMock(return_value=mock_wf)
    db.execute = AsyncMock(return_value=scalar_mock)

    mock_response = _make_openai_response(
        '{"sufficient":true,"answer":"Found 3 repos.","feedback":""}'
    )

    orchestrator = WorkflowOrchestrator(db)

    state = {
        "workflow_id": workflow_id,
        "task": "List repos",
        "actor": "test-orchestrator",
        "available_tools": [],
        "plan": [],
        "step_results": [
            {"step_order": 1, "tool_name": "list_repos", "result": [{"name": "r1"}],
             "latency_ms": 50, "error": None},
        ],
        "replan_count": 0,
        "final_answer": None,
        "error": None,
    }

    with (
        patch("mcp_gateway.services.orchestrator.openai.AsyncOpenAI") as mock_cls,
        patch.object(orchestrator, "_publish_event", new_callable=AsyncMock),
    ):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await orchestrator._reviewer_node(state)

    assert result.get("final_answer") == "Found 3 repos."
    assert mock_wf.status == WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_reviewer_node_triggers_replan():
    """Reviewer increments replan_count when results are insufficient."""
    from mcp_gateway.services.orchestrator import WorkflowOrchestrator

    db = _make_db()
    workflow_id = str(uuid.uuid4())

    mock_wf = _make_workflow(workflow_id, WorkflowStatus.RUNNING)
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none = MagicMock(return_value=mock_wf)
    db.execute = AsyncMock(return_value=scalar_mock)

    mock_response = _make_openai_response(
        '{"sufficient":false,"answer":"","feedback":"Step failed, retry."}'
    )

    orchestrator = WorkflowOrchestrator(db)

    state = {
        "workflow_id": workflow_id,
        "task": "Do something",
        "actor": "test-orchestrator",
        "available_tools": [],
        "plan": [],
        "step_results": [
            {"step_order": 1, "tool_name": "list_repos", "result": None,
             "latency_ms": 10, "error": "Timeout"},
        ],
        "replan_count": 0,
        "final_answer": None,
        "error": None,
    }

    with (
        patch("mcp_gateway.services.orchestrator.openai.AsyncOpenAI") as mock_cls,
        patch.object(orchestrator, "_publish_event", new_callable=AsyncMock),
    ):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        result = await orchestrator._reviewer_node(state)

    assert result.get("replan_count") == 1
    assert result.get("final_answer") is None


@pytest.mark.asyncio
async def test_reviewer_router_ends_on_final_answer():
    """_reviewer_router routes to END when final_answer is set."""
    from langgraph.graph import END
    from mcp_gateway.services.orchestrator import WorkflowOrchestrator

    db = _make_db()
    orchestrator = WorkflowOrchestrator(db)

    state = {
        "workflow_id": "x", "task": "t", "actor": "a",
        "available_tools": [], "plan": [], "step_results": [],
        "replan_count": 0, "final_answer": "done", "error": None,
    }
    assert orchestrator._reviewer_router(state) == END


@pytest.mark.asyncio
async def test_reviewer_router_replans_when_under_limit():
    """_reviewer_router routes back to planner when replan budget remains."""
    from mcp_gateway.services.orchestrator import WorkflowOrchestrator

    db = _make_db()
    orchestrator = WorkflowOrchestrator(db)

    state = {
        "workflow_id": "x", "task": "t", "actor": "a",
        "available_tools": [], "plan": [], "step_results": [],
        "replan_count": 0, "final_answer": None, "error": None,
    }
    assert orchestrator._reviewer_router(state) == "planner"
