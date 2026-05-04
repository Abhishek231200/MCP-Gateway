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
from mcp_gateway.services.adapters.gdrive import GoogleDriveAdapter
from mcp_gateway.services.adapters.github import GitHubAdapter
from mcp_gateway.services.adapters.kb import KnowledgeBaseAdapter
from mcp_gateway.services.adapters.registry import get_adapter
from mcp_gateway.services.adapters.slack import SlackAdapter

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


# ── Adapter registry — Week 4 types ──────────────────────────────────────────

def test_get_adapter_slack():
    server = _make_server(metadata={"adapter_type": "slack"})
    adapter = get_adapter(server)
    assert adapter.adapter_type == "slack"
    assert isinstance(adapter, SlackAdapter)


def test_get_adapter_gdrive():
    server = _make_server(metadata={"adapter_type": "gdrive"})
    adapter = get_adapter(server)
    assert adapter.adapter_type == "gdrive"
    assert isinstance(adapter, GoogleDriveAdapter)


def test_get_adapter_kb():
    server = _make_server(metadata={"adapter_type": "kb"})
    adapter = get_adapter(server)
    assert adapter.adapter_type == "kb"
    assert isinstance(adapter, KnowledgeBaseAdapter)


# ── SlackAdapter ──────────────────────────────────────────────────────────────

def test_slack_tool_definitions():
    adapter = SlackAdapter()
    tools = adapter._get_tool_definitions()
    names = {t["tool_name"] for t in tools}
    assert names == {"list_channels", "get_channel_history", "post_message", "get_user_info", "search_messages"}
    permissions = {t["tool_name"]: t["required_permission"] for t in tools}
    assert permissions["post_message"] == "write"
    assert permissions["list_channels"] == "read"


MOCK_SLACK_CHANNEL = {
    "id": "C01234ABC",
    "name": "general",
    "is_private": False,
    "is_archived": False,
    "num_members": 42,
    "topic": {"value": "Company news"},
    "purpose": {"value": "General discussion"},
    "created": 1609459200,
}

MOCK_SLACK_MESSAGE = {
    "type": "message",
    "ts": "1617000000.000100",
    "user": "U012AB3CD",
    "text": "Hello world",
    "thread_ts": None,
    "reply_count": 0,
}

MOCK_SLACK_USER = {
    "id": "U012AB3CD",
    "name": "alice",
    "real_name": "Alice Smith",
    "is_bot": False,
    "is_admin": False,
    "tz": "America/Los_Angeles",
    "profile": {
        "display_name": "alice",
        "email": "alice@example.com",
        "title": "Engineer",
    },
}


@pytest.mark.asyncio
async def test_slack_list_channels_success():
    adapter = SlackAdapter()
    server = _make_server(metadata={"adapter_type": "slack"})
    with patch(
        "mcp_gateway.services.adapters.slack._slack_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {"ok": True, "channels": [MOCK_SLACK_CHANNEL]}
        result = await adapter._execute_tool(server, "list_channels", {}, {"Authorization": "Bearer xoxb-test"})
    assert isinstance(result, list)
    assert result[0]["name"] == "general"
    assert result[0]["member_count"] == 42


@pytest.mark.asyncio
async def test_slack_get_channel_history_success():
    adapter = SlackAdapter()
    server = _make_server(metadata={"adapter_type": "slack"})
    with patch(
        "mcp_gateway.services.adapters.slack._slack_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {"ok": True, "messages": [MOCK_SLACK_MESSAGE]}
        result = await adapter._execute_tool(
            server, "get_channel_history", {"channel": "C01234ABC"}, {}
        )
    assert len(result) == 1
    assert result[0]["text"] == "Hello world"


@pytest.mark.asyncio
async def test_slack_post_message_success():
    adapter = SlackAdapter()
    server = _make_server(metadata={"adapter_type": "slack"})
    with patch(
        "mcp_gateway.services.adapters.slack._slack_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {
            "ok": True,
            "ts": "1617000001.000200",
            "channel": "C01234ABC",
            "message": MOCK_SLACK_MESSAGE,
        }
        result = await adapter._execute_tool(
            server, "post_message", {"channel": "C01234ABC", "text": "Hi!"}, {}
        )
    assert result["ts"] == "1617000001.000200"
    assert result["channel"] == "C01234ABC"


@pytest.mark.asyncio
async def test_slack_get_user_info_success():
    adapter = SlackAdapter()
    server = _make_server(metadata={"adapter_type": "slack"})
    with patch(
        "mcp_gateway.services.adapters.slack._slack_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {"ok": True, "user": MOCK_SLACK_USER}
        result = await adapter._execute_tool(
            server, "get_user_info", {"user_id": "U012AB3CD"}, {}
        )
    assert result["name"] == "alice"
    assert result["email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_slack_api_error_raises_adapter_error():
    adapter = SlackAdapter()
    server = _make_server(metadata={"adapter_type": "slack"})
    with patch(
        "mcp_gateway.services.adapters.slack._slack_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.side_effect = AdapterError("Slack API error: not_in_channel")
        with pytest.raises(AdapterError, match="not_in_channel"):
            await adapter._execute_tool(
                server, "get_channel_history", {"channel": "C99999"}, {}
            )


@pytest.mark.asyncio
async def test_slack_unknown_tool_raises():
    adapter = SlackAdapter()
    server = _make_server(metadata={"adapter_type": "slack"})
    with pytest.raises(AdapterError, match="Unknown tool"):
        await adapter._execute_tool(server, "delete_workspace", {}, {})


# ── GoogleDriveAdapter ────────────────────────────────────────────────────────

def test_gdrive_tool_definitions():
    adapter = GoogleDriveAdapter()
    tools = adapter._get_tool_definitions()
    names = {t["tool_name"] for t in tools}
    assert names == {"list_files", "get_file_metadata", "download_file", "search_files", "list_shared_drives"}
    for t in tools:
        assert t["required_permission"] == "read"


MOCK_GDRIVE_FILE = {
    "id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
    "name": "Q1 Report",
    "mimeType": "application/vnd.google-apps.spreadsheet",
    "size": None,
    "modifiedTime": "2026-04-01T10:00:00.000Z",
    "createdTime": "2026-01-01T00:00:00.000Z",
    "webViewLink": "https://docs.google.com/spreadsheets/d/1Bxi.../edit",
    "parents": ["0AJFbVN3T4yVcUk9PVA"],
    "shared": True,
    "trashed": False,
}

MOCK_GDRIVE_DRIVE = {
    "id": "0AJFbVN3T4yVcUk9PVA",
    "name": "Team Drive",
    "kind": "drive#drive",
    "createdTime": "2025-01-01T00:00:00.000Z",
}


@pytest.mark.asyncio
async def test_gdrive_list_files_success():
    adapter = GoogleDriveAdapter()
    server = _make_server(metadata={"adapter_type": "gdrive"})
    with patch(
        "mcp_gateway.services.adapters.gdrive._gdrive_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {"files": [MOCK_GDRIVE_FILE]}
        result = await adapter._execute_tool(server, "list_files", {}, {"Authorization": "Bearer ya29.test"})
    assert len(result) == 1
    assert result[0]["name"] == "Q1 Report"
    assert result[0]["mime_type"] == "application/vnd.google-apps.spreadsheet"


@pytest.mark.asyncio
async def test_gdrive_get_file_metadata_success():
    adapter = GoogleDriveAdapter()
    server = _make_server(metadata={"adapter_type": "gdrive"})
    with patch(
        "mcp_gateway.services.adapters.gdrive._gdrive_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = MOCK_GDRIVE_FILE
        result = await adapter._execute_tool(
            server, "get_file_metadata",
            {"file_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"}, {}
        )
    assert result["id"] == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
    assert result["shared"] is True


@pytest.mark.asyncio
async def test_gdrive_download_file_success():
    adapter = GoogleDriveAdapter()
    server = _make_server(metadata={"adapter_type": "gdrive"})
    with patch(
        "mcp_gateway.services.adapters.gdrive._gdrive_request", new_callable=AsyncMock
    ) as mock_meta, patch(
        "mcp_gateway.services.adapters.gdrive._gdrive_download", new_callable=AsyncMock
    ) as mock_dl:
        mock_meta.return_value = {"id": "abc", "name": "notes.txt", "mimeType": "text/plain"}
        mock_dl.return_value = "Hello from Drive"
        result = await adapter._execute_tool(
            server, "download_file", {"file_id": "abc"}, {}
        )
    assert result["content"] == "Hello from Drive"
    assert result["name"] == "notes.txt"


@pytest.mark.asyncio
async def test_gdrive_search_files_success():
    adapter = GoogleDriveAdapter()
    server = _make_server(metadata={"adapter_type": "gdrive"})
    with patch(
        "mcp_gateway.services.adapters.gdrive._gdrive_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {"files": [MOCK_GDRIVE_FILE]}
        result = await adapter._execute_tool(
            server, "search_files", {"query": "name contains 'Report'"}, {}
        )
    assert len(result) == 1


@pytest.mark.asyncio
async def test_gdrive_list_shared_drives_success():
    adapter = GoogleDriveAdapter()
    server = _make_server(metadata={"adapter_type": "gdrive"})
    with patch(
        "mcp_gateway.services.adapters.gdrive._gdrive_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {"drives": [MOCK_GDRIVE_DRIVE]}
        result = await adapter._execute_tool(server, "list_shared_drives", {}, {})
    assert result[0]["name"] == "Team Drive"


@pytest.mark.asyncio
async def test_gdrive_404_raises_adapter_error():
    adapter = GoogleDriveAdapter()
    server = _make_server(metadata={"adapter_type": "gdrive"})
    with patch(
        "mcp_gateway.services.adapters.gdrive._gdrive_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.side_effect = AdapterError("Google Drive API returned 404: File not found.", status_code=404)
        with pytest.raises(AdapterError) as exc_info:
            await adapter._execute_tool(server, "get_file_metadata", {"file_id": "bad-id"}, {})
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_gdrive_unknown_tool_raises():
    adapter = GoogleDriveAdapter()
    server = _make_server(metadata={"adapter_type": "gdrive"})
    with pytest.raises(AdapterError, match="Unknown tool"):
        await adapter._execute_tool(server, "delete_all_files", {}, {})


# ── KnowledgeBaseAdapter ──────────────────────────────────────────────────────

def test_kb_tool_definitions():
    adapter = KnowledgeBaseAdapter()
    tools = adapter._get_tool_definitions()
    names = {t["tool_name"] for t in tools}
    assert names == {"query", "search", "add_document", "list_documents", "delete_document"}
    permissions = {t["tool_name"]: t["required_permission"] for t in tools}
    assert permissions["query"] == "read"
    assert permissions["search"] == "read"
    assert permissions["add_document"] == "write"
    assert permissions["delete_document"] == "admin"


@pytest.mark.asyncio
async def test_kb_search_success():
    adapter = KnowledgeBaseAdapter()
    server = _make_server(metadata={"adapter_type": "kb"})
    server.base_url = "http://kb:8080"
    with patch(
        "mcp_gateway.services.adapters.kb._kb_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = [
            {"id": "doc1", "content": "MCP Gateway overview", "score": 0.92}
        ]
        result = await adapter._execute_tool(
            server, "search", {"query": "MCP Gateway", "top_k": 3}, {}
        )
    assert len(result) == 1
    assert result[0]["score"] == 0.92
    mock_req.assert_called_once_with(
        "POST", "http://kb:8080", "/search", {},
        json={"query": "MCP Gateway", "top_k": 3, "min_score": 0.0},
    )


@pytest.mark.asyncio
async def test_kb_search_unwraps_results_key():
    adapter = KnowledgeBaseAdapter()
    server = _make_server(metadata={"adapter_type": "kb"})
    server.base_url = "http://kb:8080"
    with patch(
        "mcp_gateway.services.adapters.kb._kb_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {"results": [{"id": "doc2", "score": 0.5}], "total": 1}
        result = await adapter._execute_tool(
            server, "search", {"query": "test"}, {}
        )
    assert result[0]["id"] == "doc2"


@pytest.mark.asyncio
async def test_kb_add_document_success():
    adapter = KnowledgeBaseAdapter()
    server = _make_server(metadata={"adapter_type": "kb"})
    server.base_url = "http://kb:8080"
    with patch(
        "mcp_gateway.services.adapters.kb._kb_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {"id": "new-doc-123", "status": "indexed"}
        result = await adapter._execute_tool(
            server, "add_document",
            {"content": "Some text", "title": "My Doc", "metadata": {"source": "upload"}},
            {},
        )
    assert result["id"] == "new-doc-123"


@pytest.mark.asyncio
async def test_kb_list_documents_success():
    adapter = KnowledgeBaseAdapter()
    server = _make_server(metadata={"adapter_type": "kb"})
    server.base_url = "http://kb:8080"
    with patch(
        "mcp_gateway.services.adapters.kb._kb_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = [{"id": "doc1"}, {"id": "doc2"}]
        result = await adapter._execute_tool(server, "list_documents", {}, {})
    assert len(result) == 2


@pytest.mark.asyncio
async def test_kb_delete_document_success():
    adapter = KnowledgeBaseAdapter()
    server = _make_server(metadata={"adapter_type": "kb"})
    server.base_url = "http://kb:8080"
    with patch(
        "mcp_gateway.services.adapters.kb._kb_request", new_callable=AsyncMock
    ) as mock_req:
        mock_req.return_value = {}
        result = await adapter._execute_tool(
            server, "delete_document", {"document_id": "doc1"}, {}
        )
    assert result == {}
    mock_req.assert_called_once_with("DELETE", "http://kb:8080", "/documents/doc1", {})


@pytest.mark.asyncio
async def test_kb_unknown_tool_raises():
    adapter = KnowledgeBaseAdapter()
    server = _make_server(metadata={"adapter_type": "kb"})
    server.base_url = "http://kb:8080"
    with pytest.raises(AdapterError, match="Unknown tool"):
        await adapter._execute_tool(server, "drop_index", {}, {})
