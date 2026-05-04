"""Integration tests for POST /tools/invoke (requires Postgres)."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

GITHUB_SERVER = {
    "name": "github-mcp-test",
    "display_name": "GitHub MCP Test",
    "base_url": "https://api.github.com",
    "auth_type": "none",
    "auth_config": {},
    "metadata": {"adapter_type": "github"},
    "capabilities": [
        {"tool_name": "list_repos", "required_permission": "read"},
        {"tool_name": "get_pr", "required_permission": "read"},
    ],
}

SLACK_SERVER = {
    "name": "slack-mcp-test",
    "display_name": "Slack MCP Test",
    "base_url": "https://slack.com/api",
    "auth_type": "none",
    "auth_config": {},
    "metadata": {"adapter_type": "slack"},
    "capabilities": [
        {"tool_name": "list_channels", "required_permission": "read"},
        {"tool_name": "post_message", "required_permission": "write"},
    ],
}

GDRIVE_SERVER = {
    "name": "gdrive-mcp-test",
    "display_name": "Google Drive MCP Test",
    "base_url": "https://www.googleapis.com/drive/v3",
    "auth_type": "none",
    "auth_config": {},
    "metadata": {"adapter_type": "gdrive"},
    "capabilities": [
        {"tool_name": "list_files", "required_permission": "read"},
        {"tool_name": "search_files", "required_permission": "read"},
    ],
}

KB_SERVER = {
    "name": "kb-mcp-test",
    "display_name": "Knowledge Base MCP Test",
    "base_url": "http://kb:8001",
    "auth_type": "none",
    "auth_config": {},
    "metadata": {"adapter_type": "kb"},
    "capabilities": [
        {"tool_name": "query", "required_permission": "read"},
        {"tool_name": "search", "required_permission": "read"},
        {"tool_name": "add_document", "required_permission": "write"},
        {"tool_name": "list_documents", "required_permission": "read"},
        {"tool_name": "delete_document", "required_permission": "admin"},
    ],
}

NO_ADAPTER_SERVER = {
    "name": "bare-server-test",
    "display_name": "Bare Server",
    "base_url": "https://example.com",
    "auth_type": "none",
    "auth_config": {},
    "metadata": {},
    "capabilities": [{"tool_name": "some_tool", "required_permission": "read"}],
}


async def _register(client: AsyncClient, payload: dict) -> str:
    resp = await client.post("/registry/servers", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_invoke_tool_success(registry_client: AsyncClient):
    server_id = await _register(registry_client, GITHUB_SERVER)

    with patch(
        "mcp_gateway.services.adapters.github._gh_request",
        new_callable=AsyncMock,
        return_value=[{
            "id": 1, "name": "repo1", "full_name": "org/repo1", "description": None,
            "html_url": None, "private": False, "default_branch": "main",
            "stargazers_count": 0, "language": "Python", "updated_at": None,
        }],
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "list_repos", "arguments": {}},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_name"] == "list_repos"
    assert data["adapter_type"] == "github"
    assert data["latency_ms"] >= 0
    assert isinstance(data["result"], list)


@pytest.mark.asyncio
async def test_invoke_tool_unknown_server(registry_client: AsyncClient):
    resp = await registry_client.post(
        "/tools/invoke",
        json={"server_id": str(uuid.uuid4()), "tool_name": "list_repos", "arguments": {}},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invoke_tool_unregistered_tool(registry_client: AsyncClient):
    server_id = await _register(registry_client, GITHUB_SERVER)
    resp = await registry_client.post(
        "/tools/invoke",
        json={"server_id": server_id, "tool_name": "nonexistent_tool", "arguments": {}},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invoke_tool_no_adapter_configured(registry_client: AsyncClient):
    server_id = await _register(registry_client, NO_ADAPTER_SERVER)
    resp = await registry_client.post(
        "/tools/invoke",
        json={"server_id": server_id, "tool_name": "some_tool", "arguments": {}},
    )
    assert resp.status_code == 503
    assert "adapter" in resp.json()["detail"].lower()


# ── Slack integration ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invoke_slack_list_channels_success(registry_client: AsyncClient):
    server_id = await _register(registry_client, SLACK_SERVER)

    mock_channels = [
        {"id": "C01", "name": "general", "is_private": False, "is_archived": False,
         "num_members": 10, "topic": {"value": "General"}, "purpose": {"value": ""}, "created": 0},
    ]
    with patch(
        "mcp_gateway.services.adapters.slack._slack_request",
        new_callable=AsyncMock,
        return_value={"ok": True, "channels": mock_channels},
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "list_channels", "arguments": {"limit": 5}},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["adapter_type"] == "slack"
    assert data["tool_name"] == "list_channels"
    assert isinstance(data["result"], list)
    assert data["result"][0]["name"] == "general"
    assert data["result"][0]["member_count"] == 10


@pytest.mark.asyncio
async def test_invoke_slack_post_message_success(registry_client: AsyncClient):
    server_id = await _register(registry_client, SLACK_SERVER)

    with patch(
        "mcp_gateway.services.adapters.slack._slack_request",
        new_callable=AsyncMock,
        return_value={
            "ok": True,
            "ts": "1617000001.000200",
            "channel": "C01",
            "message": {"type": "message", "ts": "1617000001.000200", "text": "hello"},
        },
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "post_message",
                  "arguments": {"channel": "C01", "text": "hello"}},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["adapter_type"] == "slack"
    assert data["result"]["ts"] == "1617000001.000200"


@pytest.mark.asyncio
async def test_invoke_slack_upstream_error_returns_502(registry_client: AsyncClient):
    from mcp_gateway.services.adapters.base import AdapterError
    server_id = await _register(registry_client, SLACK_SERVER)

    with patch(
        "mcp_gateway.services.adapters.slack._slack_request",
        new_callable=AsyncMock,
        side_effect=AdapterError("Slack API error: not_in_channel", status_code=None),
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "list_channels", "arguments": {}},
        )

    assert resp.status_code in (502, 503)


# ── Google Drive integration ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invoke_gdrive_list_files_success(registry_client: AsyncClient):
    server_id = await _register(registry_client, GDRIVE_SERVER)

    mock_file = {
        "id": "file123", "name": "Report.docx",
        "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size": "4096", "modifiedTime": "2026-04-01T10:00:00.000Z",
        "createdTime": "2026-01-01T00:00:00.000Z",
        "webViewLink": "https://drive.google.com/file/d/file123/view",
        "parents": ["root"], "shared": False, "trashed": False,
    }
    with patch(
        "mcp_gateway.services.adapters.gdrive._gdrive_request",
        new_callable=AsyncMock,
        return_value={"files": [mock_file]},
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "list_files", "arguments": {"page_size": 5}},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["adapter_type"] == "gdrive"
    assert data["tool_name"] == "list_files"
    assert data["result"][0]["name"] == "Report.docx"
    assert data["result"][0]["id"] == "file123"


@pytest.mark.asyncio
async def test_invoke_gdrive_search_files_success(registry_client: AsyncClient):
    server_id = await _register(registry_client, GDRIVE_SERVER)

    with patch(
        "mcp_gateway.services.adapters.gdrive._gdrive_request",
        new_callable=AsyncMock,
        return_value={"files": []},
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "search_files",
                  "arguments": {"query": "name contains 'Report'"}},
        )

    assert resp.status_code == 200
    assert resp.json()["adapter_type"] == "gdrive"
    assert isinstance(resp.json()["result"], list)


@pytest.mark.asyncio
async def test_invoke_gdrive_404_returns_502(registry_client: AsyncClient):
    from mcp_gateway.services.adapters.base import AdapterError
    server_id = await _register(registry_client, GDRIVE_SERVER)

    with patch(
        "mcp_gateway.services.adapters.gdrive._gdrive_request",
        new_callable=AsyncMock,
        side_effect=AdapterError("Google Drive API returned 404: File not found.", status_code=404),
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "list_files", "arguments": {}},
        )

    assert resp.status_code in (404, 502)


# ── Knowledge Base integration ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invoke_kb_search_success(registry_client: AsyncClient):
    server_id = await _register(registry_client, KB_SERVER)

    mock_results = [
        {"id": "doc-1", "content": "MCP Gateway architecture overview", "score": 0.91,
         "title": "Architecture", "metadata": {"source": "wiki"}},
    ]
    with patch(
        "mcp_gateway.services.adapters.kb._kb_request",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "search",
                  "arguments": {"query": "MCP Gateway", "top_k": 3}},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["adapter_type"] == "kb"
    assert data["tool_name"] == "search"
    assert data["result"][0]["score"] == 0.91


@pytest.mark.asyncio
async def test_invoke_kb_add_document_success(registry_client: AsyncClient):
    server_id = await _register(registry_client, KB_SERVER)

    with patch(
        "mcp_gateway.services.adapters.kb._kb_request",
        new_callable=AsyncMock,
        return_value={"id": "doc-new", "status": "indexed"},
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "add_document",
                  "arguments": {"content": "Week 4 notes", "title": "Week 4"}},
        )

    assert resp.status_code == 200
    assert resp.json()["result"]["id"] == "doc-new"


@pytest.mark.asyncio
async def test_invoke_kb_list_documents_success(registry_client: AsyncClient):
    server_id = await _register(registry_client, KB_SERVER)

    with patch(
        "mcp_gateway.services.adapters.kb._kb_request",
        new_callable=AsyncMock,
        return_value=[{"id": "doc-1"}, {"id": "doc-2"}],
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "list_documents", "arguments": {}},
        )

    assert resp.status_code == 200
    assert len(resp.json()["result"]) == 2


@pytest.mark.asyncio
async def test_invoke_kb_delete_document_success(registry_client: AsyncClient):
    server_id = await _register(registry_client, KB_SERVER)

    with patch(
        "mcp_gateway.services.adapters.kb._kb_request",
        new_callable=AsyncMock,
        return_value={},
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "delete_document",
                  "arguments": {"document_id": "doc-1"}},
        )

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_invoke_kb_query_success(registry_client: AsyncClient):
    server_id = await _register(registry_client, KB_SERVER)

    mock_rag_response = {
        "answer": "The adapter layer dispatches tool calls to the correct MCP server adapter.",
        "sources": [{"id": "doc-1", "title": "Architecture", "score": 0.87}],
        "question": "How does the adapter layer work?",
    }
    with patch(
        "mcp_gateway.services.adapters.kb._kb_request",
        new_callable=AsyncMock,
        return_value=mock_rag_response,
    ):
        resp = await registry_client.post(
            "/tools/invoke",
            json={"server_id": server_id, "tool_name": "query",
                  "arguments": {"question": "How does the adapter layer work?"}},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["adapter_type"] == "kb"
    assert data["tool_name"] == "query"
    assert "answer" in data["result"]
    assert isinstance(data["result"]["sources"], list)


# ── Credential error path ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invoke_credential_error_returns_503(registry_client: AsyncClient):
    """Server with api_key auth but no env var set → 503."""
    server = {
        **SLACK_SERVER,
        "name": "slack-no-creds-test",
        "auth_type": "api_key",
        "auth_config": {"token_env_var": "NONEXISTENT_SLACK_TOKEN_XYZ"},
    }
    server_id = await _register(registry_client, server)
    resp = await registry_client.post(
        "/tools/invoke",
        json={"server_id": server_id, "tool_name": "list_channels", "arguments": {}},
    )
    assert resp.status_code == 503
    assert "NONEXISTENT_SLACK_TOKEN_XYZ" in resp.json()["detail"]
