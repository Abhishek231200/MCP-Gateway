"""Jira adapter — wraps Jira Cloud REST API v3."""

import base64
import os
from typing import Any

import httpx
import structlog

from mcp_gateway.models.registry import McpServer
from mcp_gateway.services.adapters.base import AdapterError, BaseAdapter

logger = structlog.get_logger()

_TIMEOUT = 15.0

_TOOL_DEFINITIONS = [
    {
        "tool_name": "get_issue",
        "description": "Get a Jira issue by key (e.g. PROJ-142)",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Issue key e.g. PROJ-142"},
            },
            "required": ["issue_key"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "read",
    },
    {
        "tool_name": "search_issues",
        "description": "Search Jira issues using JQL",
        "input_schema": {
            "type": "object",
            "properties": {
                "jql": {"type": "string", "description": "JQL query e.g. 'project=PROJ AND status=Open'"},
                "max_results": {"type": "integer", "default": 20, "maximum": 50},
                "fields": {"type": "string", "description": "Comma-separated fields to return (default: summary,status,assignee,priority)"},
            },
            "required": ["jql"],
        },
        "output_schema": {"type": "array"},
        "required_permission": "read",
    },
    {
        "tool_name": "list_projects",
        "description": "List all Jira projects accessible to the user",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "default": 50},
            },
        },
        "output_schema": {"type": "array"},
        "required_permission": "read",
    },
    {
        "tool_name": "create_issue",
        "description": "Create a new Jira issue",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_key": {"type": "string", "description": "Project key e.g. PROJ"},
                "summary": {"type": "string"},
                "description": {"type": "string"},
                "issue_type": {"type": "string", "default": "Task", "description": "Issue type: Task, Bug, Story, Epic"},
                "priority": {"type": "string", "description": "Priority: Highest, High, Medium, Low, Lowest"},
                "assignee": {"type": "string", "description": "Assignee account ID or email"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project_key", "summary"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "write",
    },
    {
        "tool_name": "update_issue",
        "description": "Update fields on an existing Jira issue",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string"},
                "summary": {"type": "string"},
                "description": {"type": "string"},
                "priority": {"type": "string"},
                "assignee": {"type": "string", "description": "Assignee account ID"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["issue_key"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "write",
    },
    {
        "tool_name": "transition_issue",
        "description": "Transition a Jira issue to a new status (e.g. In Progress, Done, Closed)",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string"},
                "status": {"type": "string", "description": "Target status name e.g. 'In Progress', 'Done', 'Closed'"},
            },
            "required": ["issue_key", "status"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "write",
    },
    {
        "tool_name": "add_comment",
        "description": "Add a comment to a Jira issue",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string"},
                "body": {"type": "string", "description": "Comment text"},
            },
            "required": ["issue_key", "body"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "write",
    },
    {
        "tool_name": "get_comments",
        "description": "Get all comments on a Jira issue",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string"},
            },
            "required": ["issue_key"],
        },
        "output_schema": {"type": "array"},
        "required_permission": "read",
    },
    {
        "tool_name": "assign_issue",
        "description": "Assign a Jira issue to a user",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string"},
                "account_id": {"type": "string", "description": "Jira account ID of the assignee"},
            },
            "required": ["issue_key", "account_id"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "write",
    },
    {
        "tool_name": "get_sprint_issues",
        "description": "Get all issues in the active sprint for a project board",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_key": {"type": "string"},
                "max_results": {"type": "integer", "default": 50},
            },
            "required": ["project_key"],
        },
        "output_schema": {"type": "array"},
        "required_permission": "read",
    },
]


def _normalize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    fields = issue.get("fields") or {}
    return {
        "key": issue.get("key"),
        "id": issue.get("id"),
        "url": issue.get("self", "").replace("/rest/api/3/issue/", "/browse/").split("/rest/")[0] + f"/browse/{issue.get('key', '')}",
        "summary": fields.get("summary"),
        "description": _extract_text(fields.get("description")),
        "status": (fields.get("status") or {}).get("name"),
        "issue_type": (fields.get("issuetype") or {}).get("name"),
        "priority": (fields.get("priority") or {}).get("name"),
        "assignee": (fields.get("assignee") or {}).get("displayName"),
        "reporter": (fields.get("reporter") or {}).get("displayName"),
        "labels": fields.get("labels", []),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "due_date": fields.get("duedate"),
        "resolution": (fields.get("resolution") or {}).get("name"),
    }


def _extract_text(doc: Any) -> str:
    """Convert Jira Atlassian Document Format (ADF) to plain text."""
    if doc is None:
        return ""
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        node_type = doc.get("type", "")
        if node_type == "text":
            return doc.get("text", "")
        parts = [_extract_text(child) for child in (doc.get("content") or [])]
        joiner = "\n" if node_type in ("paragraph", "heading", "bulletList", "orderedList", "listItem") else ""
        return joiner.join(p for p in parts if p)
    return ""


class JiraAdapter(BaseAdapter):
    @property
    def adapter_type(self) -> str:
        return "jira"

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        return _TOOL_DEFINITIONS

    def _make_auth_headers(self, server: McpServer) -> dict[str, str]:
        """Build Basic Auth headers from JIRA_API_TOKEN + JIRA_USER_EMAIL env vars."""
        token = os.environ.get((server.auth_config or {}).get("token_env_var", "JIRA_API_TOKEN"), "")
        email = os.environ.get("JIRA_USER_EMAIL", "")
        if not token or not email:
            from mcp_gateway.services.adapters.credentials import CredentialResolutionError
            raise CredentialResolutionError("Jira requires JIRA_API_TOKEN and JIRA_USER_EMAIL env vars")
        encoded = base64.b64encode(f"{email}:{token}".encode()).decode()
        return {"Authorization": f"Basic {encoded}", "Accept": "application/json", "Content-Type": "application/json"}

    def _base_url(self, server: McpServer) -> str:
        return (server.base_url or "").rstrip("/")

    async def _jira_request(
        self,
        method: str,
        server: McpServer,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        headers = self._make_auth_headers(server)
        url = f"{self._base_url(server)}/rest/api/3{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.request(method, url, headers=headers, params=params, json=json)
        if resp.status_code == 204:
            return {}
        if resp.status_code >= 400:
            raise AdapterError(f"Jira API returned {resp.status_code}: {resp.text[:300]}", status_code=resp.status_code)
        return resp.json()

    async def _execute_tool(
        self,
        server: McpServer,
        tool_name: str,
        arguments: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        match tool_name:
            case "get_issue":       return await self._get_issue(server, arguments)
            case "search_issues":   return await self._search_issues(server, arguments)
            case "list_projects":   return await self._list_projects(server, arguments)
            case "create_issue":    return await self._create_issue(server, arguments)
            case "update_issue":    return await self._update_issue(server, arguments)
            case "transition_issue": return await self._transition_issue(server, arguments)
            case "add_comment":     return await self._add_comment(server, arguments)
            case "get_comments":    return await self._get_comments(server, arguments)
            case "assign_issue":    return await self._assign_issue(server, arguments)
            case "get_sprint_issues": return await self._get_sprint_issues(server, arguments)
            case _:
                raise AdapterError(f"Unknown tool '{tool_name}' for Jira adapter")

    async def _get_issue(self, server: McpServer, args: dict[str, Any]) -> dict[str, Any]:
        data = await self._jira_request("GET", server, f"/issue/{args['issue_key']}")
        return _normalize_issue(data)

    async def _search_issues(self, server: McpServer, args: dict[str, Any]) -> list[dict[str, Any]]:
        fields = args.get("fields", "summary,status,assignee,priority,description,labels,created,updated")
        data = await self._jira_request("GET", server, "/search/jql", params={
            "jql": args["jql"],
            "maxResults": args.get("max_results", 20),
            "fields": fields,
        })
        return [_normalize_issue(i) for i in (data.get("issues") or [])]

    async def _list_projects(self, server: McpServer, args: dict[str, Any]) -> list[dict[str, Any]]:
        data = await self._jira_request("GET", server, "/project/search", params={"maxResults": args.get("max_results", 50)})
        return [
            {"key": p.get("key"), "name": p.get("name"), "id": p.get("id"),
             "type": p.get("projectTypeKey"), "lead": (p.get("lead") or {}).get("displayName")}
            for p in (data.get("values") or [])
        ]

    async def _create_issue(self, server: McpServer, args: dict[str, Any]) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "project": {"key": args["project_key"]},
            "summary": args["summary"],
            "issuetype": {"name": args.get("issue_type", "Task")},
        }
        if desc := args.get("description"):
            fields["description"] = {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": desc}]}
            ]}
        if priority := args.get("priority"):
            fields["priority"] = {"name": priority}
        if labels := args.get("labels"):
            fields["labels"] = labels
        data = await self._jira_request("POST", server, "/issue", json={"fields": fields})
        return {"key": data.get("key"), "id": data.get("id"), "url": f"{self._base_url(server)}/browse/{data.get('key')}"}

    async def _update_issue(self, server: McpServer, args: dict[str, Any]) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if summary := args.get("summary"):
            fields["summary"] = summary
        if desc := args.get("description"):
            fields["description"] = {"type": "doc", "version": 1, "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": desc}]}
            ]}
        if priority := args.get("priority"):
            fields["priority"] = {"name": priority}
        if labels := args.get("labels"):
            fields["labels"] = labels
        if assignee := args.get("assignee"):
            fields["assignee"] = {"accountId": assignee}
        await self._jira_request("PUT", server, f"/issue/{args['issue_key']}", json={"fields": fields})
        return {"key": args["issue_key"], "updated": True}

    async def _transition_issue(self, server: McpServer, args: dict[str, Any]) -> dict[str, Any]:
        issue_key = args["issue_key"]
        target_status = args["status"].lower()
        transitions = await self._jira_request("GET", server, f"/issue/{issue_key}/transitions")
        match = next(
            (t for t in (transitions.get("transitions") or [])
             if t.get("name", "").lower() == target_status or
             (t.get("to") or {}).get("name", "").lower() == target_status),
            None,
        )
        if not match:
            available = [t.get("name") for t in (transitions.get("transitions") or [])]
            raise AdapterError(f"Transition '{args['status']}' not found. Available: {available}")
        await self._jira_request("POST", server, f"/issue/{issue_key}/transitions", json={"transition": {"id": match["id"]}})
        return {"key": issue_key, "transitioned_to": args["status"]}

    async def _add_comment(self, server: McpServer, args: dict[str, Any]) -> dict[str, Any]:
        body = {"type": "doc", "version": 1, "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": args["body"]}]}
        ]}
        data = await self._jira_request("POST", server, f"/issue/{args['issue_key']}/comment", json={"body": body})
        return {
            "id": data.get("id"),
            "author": (data.get("author") or {}).get("displayName"),
            "created": data.get("created"),
        }

    async def _get_comments(self, server: McpServer, args: dict[str, Any]) -> list[dict[str, Any]]:
        data = await self._jira_request("GET", server, f"/issue/{args['issue_key']}/comment")
        return [
            {
                "id": c.get("id"),
                "author": (c.get("author") or {}).get("displayName"),
                "body": _extract_text(c.get("body")),
                "created": c.get("created"),
                "updated": c.get("updated"),
            }
            for c in (data.get("comments") or [])
        ]

    async def _assign_issue(self, server: McpServer, args: dict[str, Any]) -> dict[str, Any]:
        await self._jira_request("PUT", server, f"/issue/{args['issue_key']}/assignee",
                                  json={"accountId": args["account_id"]})
        return {"key": args["issue_key"], "assigned_to": args["account_id"]}

    async def _get_sprint_issues(self, server: McpServer, args: dict[str, Any]) -> list[dict[str, Any]]:
        jql = f"project = {args['project_key']} AND sprint in openSprints() ORDER BY priority ASC"
        return await self._search_issues(server, {"jql": jql, "max_results": args.get("max_results", 50)})
