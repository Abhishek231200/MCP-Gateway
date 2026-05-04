"""Integration tests for the MCP Registry API."""

import pytest
from httpx import AsyncClient

# ── Fixtures ──────────────────────────────────────────────────────────────────

GITHUB_SERVER = {
    "name": "github-mcp-reg-test",
    "display_name": "GitHub MCP",
    "description": "GitHub tool server",
    "base_url": "http://github-mcp:3000",
    "version": "1.0.0",
    "auth_type": "api_key",
    "auth_config": {"token_env_var": "GITHUB_TOKEN"},
    "metadata": {"owner": "platform-team"},
    "capabilities": [
        {
            "tool_name": "create_issue",
            "description": "Create a GitHub issue",
            "input_schema": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["repo", "title"],
            },
            "output_schema": {"type": "object", "properties": {"issue_url": {"type": "string"}}},
            "required_permission": "write",
        },
        {
            "tool_name": "list_repos",
            "description": "List user repositories",
            "input_schema": {"type": "object", "properties": {}},
            "output_schema": {"type": "array"},
            "required_permission": "read",
        },
    ],
}

SLACK_SERVER = {
    "name": "slack-mcp-reg-test",
    "display_name": "Slack MCP",
    "base_url": "http://slack-mcp:3001",
    "capabilities": [
        {
            "tool_name": "send_message",
            "description": "Post a message to a channel",
            "input_schema": {
                "type": "object",
                "properties": {"channel": {"type": "string"}, "text": {"type": "string"}},
                "required": ["channel", "text"],
            },
            "output_schema": {},
            "required_permission": "write",
        }
    ],
}


# ── Register ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_server(registry_client: AsyncClient) -> None:
    resp = await registry_client.post("/registry/servers", json=GITHUB_SERVER)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "github-mcp-reg-test"
    assert data["health_status"] == "unknown"
    assert len(data["capabilities"]) == 2
    tool_names = {c["tool_name"] for c in data["capabilities"]}
    assert tool_names == {"create_issue", "list_repos"}


@pytest.mark.asyncio
async def test_register_duplicate_name_rejected(registry_client: AsyncClient) -> None:
    await registry_client.post("/registry/servers", json=GITHUB_SERVER)
    resp = await registry_client.post("/registry/servers", json=GITHUB_SERVER)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_invalid_name_rejected(registry_client: AsyncClient) -> None:
    bad = {**GITHUB_SERVER, "name": "GitHub MCP"}  # spaces not allowed
    resp = await registry_client.post("/registry/servers", json=bad)
    assert resp.status_code == 422


# ── Read ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_server(registry_client: AsyncClient) -> None:
    created = (await registry_client.post("/registry/servers", json=GITHUB_SERVER)).json()
    server_id = created["id"]

    resp = await registry_client.get(f"/registry/servers/{server_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == server_id


@pytest.mark.asyncio
async def test_get_server_not_found(registry_client: AsyncClient) -> None:
    resp = await registry_client.get("/registry/servers/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_servers(registry_client: AsyncClient) -> None:
    await registry_client.post("/registry/servers", json=GITHUB_SERVER)
    await registry_client.post("/registry/servers", json=SLACK_SERVER)

    resp = await registry_client.get("/registry/servers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2
    names = {s["name"] for s in data["items"]}
    assert {"github-mcp-reg-test", "slack-mcp-reg-test"}.issubset(names)


# ── Update ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_server(registry_client: AsyncClient) -> None:
    created = (await registry_client.post("/registry/servers", json=GITHUB_SERVER)).json()
    server_id = created["id"]

    resp = await registry_client.patch(
        f"/registry/servers/{server_id}",
        json={"display_name": "GitHub MCP v2", "version": "2.0.0"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["display_name"] == "GitHub MCP v2"
    assert data["version"] == "2.0.0"
    assert data["name"] == "github-mcp-reg-test"  # unchanged


@pytest.mark.asyncio
async def test_deactivate_server(registry_client: AsyncClient) -> None:
    created = (await registry_client.post("/registry/servers", json=GITHUB_SERVER)).json()
    server_id = created["id"]

    await registry_client.patch(f"/registry/servers/{server_id}", json={"is_active": False})

    # Should not appear in active-only list
    resp = await registry_client.get("/registry/servers?active_only=true")
    ids = {s["id"] for s in resp.json()["items"]}
    assert server_id not in ids

    # Should appear when active_only=false
    resp = await registry_client.get("/registry/servers?active_only=false")
    ids = {s["id"] for s in resp.json()["items"]}
    assert server_id in ids


# ── Delete ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deregister_server(registry_client: AsyncClient) -> None:
    created = (await registry_client.post("/registry/servers", json=GITHUB_SERVER)).json()
    server_id = created["id"]

    resp = await registry_client.delete(f"/registry/servers/{server_id}")
    assert resp.status_code == 204

    resp = await registry_client.get(f"/registry/servers/{server_id}")
    assert resp.status_code == 404


# ── Capabilities ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_replace_capabilities(registry_client: AsyncClient) -> None:
    created = (await registry_client.post("/registry/servers", json=GITHUB_SERVER)).json()
    server_id = created["id"]

    new_caps = [
        {
            "tool_name": "merge_pr",
            "description": "Merge a pull request",
            "input_schema": {"type": "object", "properties": {"pr_id": {"type": "integer"}}},
            "output_schema": {},
            "required_permission": "admin",
        }
    ]
    resp = await registry_client.put(
        f"/registry/servers/{server_id}/capabilities", json=new_caps
    )
    assert resp.status_code == 200
    caps = resp.json()["capabilities"]
    assert len(caps) == 1
    assert caps[0]["tool_name"] == "merge_pr"


# ── Tool search ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_tools_all(registry_client: AsyncClient) -> None:
    await registry_client.post("/registry/servers", json=GITHUB_SERVER)
    await registry_client.post("/registry/servers", json=SLACK_SERVER)

    resp = await registry_client.get("/registry/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3  # at least create_issue + list_repos + send_message
    tool_names = {t["tool_name"] for t in data["items"]}
    assert {"create_issue", "list_repos", "send_message"}.issubset(tool_names)


@pytest.mark.asyncio
async def test_search_tools_by_name(registry_client: AsyncClient) -> None:
    await registry_client.post("/registry/servers", json=GITHUB_SERVER)
    await registry_client.post("/registry/servers", json=SLACK_SERVER)

    resp = await registry_client.get("/registry/tools?name=issue")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    tool_names = {t["tool_name"] for t in data["items"]}
    assert "create_issue" in tool_names


@pytest.mark.asyncio
async def test_search_tools_by_permission(registry_client: AsyncClient) -> None:
    await registry_client.post("/registry/servers", json=GITHUB_SERVER)
    await registry_client.post("/registry/servers", json=SLACK_SERVER)

    resp = await registry_client.get("/registry/tools?permission=read")
    assert resp.status_code == 200
    data = resp.json()
    assert all(t["required_permission"] == "read" for t in data["items"])
    tool_names = {t["tool_name"] for t in data["items"]}
    assert "list_repos" in tool_names


# ── Health scheduler unit test ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_marks_healthy(registry_client: AsyncClient, db_session) -> None:
    """Newly registered servers start as unknown; probe logic classifies correctly."""
    from unittest.mock import AsyncMock, patch

    from mcp_gateway.models.registry import HealthStatus
    from mcp_gateway.services.health_scheduler import _probe

    created = (await registry_client.post("/registry/servers", json=GITHUB_SERVER)).json()
    assert created["health_status"] == "unknown"

    # Verify the probe function itself classifies 2xx as healthy
    with patch("mcp_gateway.services.health_scheduler.httpx.AsyncClient") as mock_cls:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_cls.return_value = mock_client

        status = await _probe("http://fake-server:3000")

    assert status == HealthStatus.HEALTHY
