"""Unit tests for the adapter abstraction layer (no real HTTP, no DB)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_gateway.models.registry import AuthType, McpServer
from mcp_gateway.services.adapters import AdapterNotFoundError
from mcp_gateway.services.adapters.base import AdapterError
from mcp_gateway.services.adapters.credentials import (
    CredentialResolutionError,
    resolve_credentials,
)
from mcp_gateway.services.adapters.github import GitHubAdapter
from mcp_gateway.services.adapters.registry import get_adapter

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_server(
    *,
    auth_type: AuthType = AuthType.NONE,
    auth_config: dict | None = None,
    metadata: dict | None = None,
    name: str = "test-server",
) -> McpServer:
    server = MagicMock(spec=McpServer)
    server.id = uuid.uuid4()
    server.name = name
    server.auth_type = auth_type
    server.auth_config = auth_config or {}
    server.metadata_ = metadata or {}
    return server


# ── credentials.py ────────────────────────────────────────────────────────────

def test_resolve_credentials_none_auth():
    server = _make_server(auth_type=AuthType.NONE)
    assert resolve_credentials(server) == {}


def test_resolve_credentials_api_key(monkeypatch):
    monkeypatch.setenv("MY_API_TOKEN", "secret123")
    server = _make_server(
        auth_type=AuthType.API_KEY,
        auth_config={"token_env_var": "MY_API_TOKEN"},
    )
    headers = resolve_credentials(server)
    assert headers == {"Authorization": "Bearer secret123"}


def test_resolve_credentials_custom_header(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "tok")
    server = _make_server(
        auth_type=AuthType.API_KEY,
        auth_config={"token_env_var": "MY_TOKEN", "header_name": "X-Api-Key", "header_prefix": ""},
    )
    headers = resolve_credentials(server)
    assert headers == {"X-Api-Key": " tok"}


def test_resolve_credentials_missing_env_var(monkeypatch):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    server = _make_server(
        auth_type=AuthType.API_KEY,
        auth_config={"token_env_var": "MISSING_VAR"},
    )
    with pytest.raises(CredentialResolutionError, match="MISSING_VAR"):
        resolve_credentials(server)


def test_resolve_credentials_missing_token_env_var_key():
    server = _make_server(
        auth_type=AuthType.API_KEY,
        auth_config={},  # no token_env_var key
    )
    with pytest.raises(CredentialResolutionError, match="token_env_var"):
        resolve_credentials(server)


# ── adapter registry ──────────────────────────────────────────────────────────

def test_get_adapter_github():
    server = _make_server(metadata={"adapter_type": "github"})
    adapter = get_adapter(server)
    assert adapter.adapter_type == "github"
    assert isinstance(adapter, GitHubAdapter)


def test_get_adapter_unknown_type():
    server = _make_server(metadata={"adapter_type": "unknown-xyz"})
    with pytest.raises(AdapterNotFoundError, match="unknown-xyz"):
        get_adapter(server)


def test_get_adapter_missing_type():
    server = _make_server(metadata={})
    with pytest.raises(AdapterNotFoundError):
        get_adapter(server)


# ── GitHubAdapter._get_tool_definitions ───────────────────────────────────────

def test_github_tool_definitions():
    adapter = GitHubAdapter()
    tools = adapter._get_tool_definitions()
    names = {t["tool_name"] for t in tools}
    assert names == {"list_repos", "get_pr", "list_prs", "get_issue", "list_issues", "get_file_contents"}
    for t in tools:
        assert t["required_permission"] == "read"


# ── GitHubAdapter._execute_tool (mock httpx) ──────────────────────────────────

MOCK_REPO = {
    "id": 1, "name": "my-repo", "full_name": "org/my-repo",
    "description": "test", "html_url": "https://github.com/org/my-repo",
    "private": False, "default_branch": "main", "stargazers_count": 10,
    "language": "Python", "updated_at": "2026-04-01T00:00:00Z",
}

MOCK_PR = {
    "number": 42, "title": "Fix bug", "state": "open",
    "html_url": "https://github.com/org/repo/pull/42",
    "user": {"login": "arsh"}, "body": "fixes it",
    "head": {"ref": "fix-branch"}, "base": {"ref": "main"},
    "draft": False, "created_at": "2026-04-01T00:00:00Z",
    "updated_at": "2026-04-01T00:00:00Z", "merged_at": None,
}

MOCK_ISSUE = {
    "number": 7, "title": "Bug report", "state": "open",
    "html_url": "https://github.com/org/repo/issues/7",
    "user": {"login": "user1"}, "body": "something broke",
    "labels": [{"name": "bug"}],
    "created_at": "2026-04-01T00:00:00Z",
    "updated_at": "2026-04-01T00:00:00Z", "closed_at": None,
}


@pytest.mark.asyncio
async def test_github_list_repos_success():
    adapter = GitHubAdapter()
    server = _make_server(metadata={"adapter_type": "github"})
    with patch("mcp_gateway.services.adapters.github._gh_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = [MOCK_REPO]
        result = await adapter._execute_tool(server, "list_repos", {}, {"Authorization": "Bearer tok"})
    assert isinstance(result, list)
    assert result[0]["name"] == "my-repo"
    assert "node_id" not in result[0]


@pytest.mark.asyncio
async def test_github_get_pr_success():
    adapter = GitHubAdapter()
    server = _make_server(metadata={"adapter_type": "github"})
    with patch("mcp_gateway.services.adapters.github._gh_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = MOCK_PR
        result = await adapter._execute_tool(
            server, "get_pr", {"owner": "org", "repo": "repo", "number": 42}, {}
        )
    assert result["number"] == 42
    assert result["title"] == "Fix bug"


@pytest.mark.asyncio
async def test_github_list_issues_filters_prs():
    """list_issues must exclude items that have a pull_request key."""
    adapter = GitHubAdapter()
    server = _make_server(metadata={"adapter_type": "github"})
    pr_as_issue = {**MOCK_ISSUE, "number": 99, "pull_request": {"url": "..."}}
    with patch("mcp_gateway.services.adapters.github._gh_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = [MOCK_ISSUE, pr_as_issue]
        result = await adapter._execute_tool(
            server, "list_issues", {"owner": "org", "repo": "repo"}, {}
        )
    assert len(result) == 1
    assert result[0]["number"] == 7


@pytest.mark.asyncio
async def test_github_adapter_404_raises_adapter_error():
    adapter = GitHubAdapter()
    server = _make_server(metadata={"adapter_type": "github"})
    with patch("mcp_gateway.services.adapters.github._gh_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = AdapterError("GitHub API returned 404: Not Found", status_code=404)
        with pytest.raises(AdapterError) as exc_info:
            await adapter._execute_tool(
                server, "get_pr", {"owner": "o", "repo": "r", "number": 1}, {}
            )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_github_unknown_tool_raises():
    adapter = GitHubAdapter()
    server = _make_server(metadata={"adapter_type": "github"})
    with pytest.raises(AdapterError, match="Unknown tool"):
        await adapter._execute_tool(server, "delete_everything", {}, {})


# ── BaseAdapter.invoke_tool — audit log always written ────────────────────────

@pytest.mark.asyncio
async def test_invoke_tool_writes_audit_log_on_success():
    adapter = GitHubAdapter()
    server = _make_server(auth_type=AuthType.NONE, metadata={"adapter_type": "github"})

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    with patch.object(adapter, "_execute_tool", new_callable=AsyncMock, return_value={"repos": []}):
        result = await adapter.invoke_tool(server, "list_repos", {}, db, actor="test")

    db.add.assert_called_once()
    audit_entry = db.add.call_args[0][0]
    from mcp_gateway.models.audit import AuditAction, AuditLog
    assert isinstance(audit_entry, AuditLog)
    assert audit_entry.action == AuditAction.TOOL_CALL
    assert audit_entry.allowed is True
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_invoke_tool_writes_audit_log_on_failure():
    adapter = GitHubAdapter()
    server = _make_server(auth_type=AuthType.NONE, metadata={"adapter_type": "github"})

    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch.object(
        adapter, "_execute_tool",
        new_callable=AsyncMock,
        side_effect=AdapterError("boom", status_code=500),
    ), pytest.raises(AdapterError):
        await adapter.invoke_tool(server, "list_repos", {}, db, actor="test")

    db.add.assert_called_once()
    audit_entry = db.add.call_args[0][0]
    from mcp_gateway.models.audit import AuditAction
    assert audit_entry.action == AuditAction.TOOL_BLOCKED
    assert audit_entry.allowed is False
