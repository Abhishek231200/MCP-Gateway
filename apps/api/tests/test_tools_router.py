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
