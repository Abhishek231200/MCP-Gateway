"""GitHub adapter — wraps GitHub REST API v3."""

from typing import Any

import httpx
import structlog

from mcp_gateway.models.registry import McpServer
from mcp_gateway.services.adapters.base import AdapterError, BaseAdapter

logger = structlog.get_logger()

GITHUB_API_BASE = "https://api.github.com"
_TIMEOUT = 10.0

_TOOL_DEFINITIONS = [
    {
        "tool_name": "list_repos",
        "description": "List repositories for the authenticated user or an organization",
        "input_schema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": "Organization name (omit for user repos)"},
                "per_page": {"type": "integer", "default": 30, "maximum": 100},
            },
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
    {
        "tool_name": "get_pr",
        "description": "Get a single pull request by number",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "number": {"type": "integer"},
            },
            "required": ["owner", "repo", "number"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "read",
    },
    {
        "tool_name": "list_prs",
        "description": "List pull requests for a repository",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "per_page": {"type": "integer", "default": 30, "maximum": 100},
            },
            "required": ["owner", "repo"],
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
    {
        "tool_name": "get_issue",
        "description": "Get a single issue by number",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "number": {"type": "integer"},
            },
            "required": ["owner", "repo", "number"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "read",
    },
    {
        "tool_name": "list_issues",
        "description": "List issues for a repository",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"},
                "per_page": {"type": "integer", "default": 30, "maximum": 100},
            },
            "required": ["owner", "repo"],
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
    {
        "tool_name": "get_file_contents",
        "description": "Get the contents of a file in a repository",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string"},
                "ref": {"type": "string", "description": "Branch, tag, or commit SHA (default: repo default branch)"},
            },
            "required": ["owner", "repo", "path"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "read",
    },
]


def _normalize_repo(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "name": r.get("name"),
        "full_name": r.get("full_name"),
        "description": r.get("description"),
        "url": r.get("html_url"),
        "private": r.get("private"),
        "default_branch": r.get("default_branch"),
        "stars": r.get("stargazers_count"),
        "language": r.get("language"),
        "updated_at": r.get("updated_at"),
    }


def _normalize_pr(pr: dict) -> dict:
    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "url": pr.get("html_url"),
        "author": (pr.get("user") or {}).get("login"),
        "body": pr.get("body"),
        "head": (pr.get("head") or {}).get("ref"),
        "base": (pr.get("base") or {}).get("ref"),
        "draft": pr.get("draft"),
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
        "merged_at": pr.get("merged_at"),
    }


def _normalize_issue(issue: dict) -> dict:
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "url": issue.get("html_url"),
        "author": (issue.get("user") or {}).get("login"),
        "body": issue.get("body"),
        "labels": [lb.get("name") for lb in (issue.get("labels") or [])],
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"),
    }


def _normalize_file(f: dict) -> dict:
    import base64

    content_raw = f.get("content", "")
    encoding = f.get("encoding", "")
    content: str | None = None
    if encoding == "base64" and content_raw:
        try:
            content = base64.b64decode(content_raw).decode("utf-8", errors="replace")
        except Exception:
            content = content_raw
    else:
        content = content_raw

    return {
        "name": f.get("name"),
        "path": f.get("path"),
        "sha": f.get("sha"),
        "size": f.get("size"),
        "url": f.get("html_url"),
        "content": content,
        "encoding": encoding,
    }


async def _gh_request(
    method: str,
    path: str,
    headers: dict[str, str],
    params: dict | None = None,
) -> Any:
    default_headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    merged = {**default_headers, **headers}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.request(method, f"{GITHUB_API_BASE}{path}", headers=merged, params=params)
    if resp.status_code >= 400:
        raise AdapterError(
            f"GitHub API returned {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
        )
    return resp.json()


class GitHubAdapter(BaseAdapter):
    @property
    def adapter_type(self) -> str:
        return "github"

    def _get_tool_definitions(self) -> list[dict]:
        return _TOOL_DEFINITIONS

    async def _execute_tool(
        self,
        server: McpServer,
        tool_name: str,
        arguments: dict,
        headers: dict[str, str],
    ) -> Any:
        match tool_name:
            case "list_repos":
                return await self._list_repos(arguments, headers)
            case "get_pr":
                return await self._get_pr(arguments, headers)
            case "list_prs":
                return await self._list_prs(arguments, headers)
            case "get_issue":
                return await self._get_issue(arguments, headers)
            case "list_issues":
                return await self._list_issues(arguments, headers)
            case "get_file_contents":
                return await self._get_file_contents(arguments, headers)
            case _:
                raise AdapterError(f"Unknown tool '{tool_name}' for GitHub adapter")

    async def _list_repos(self, args: dict, headers: dict) -> list[dict]:
        org = args.get("org")
        per_page = args.get("per_page", 30)
        path = f"/orgs/{org}/repos" if org else "/user/repos"
        data = await _gh_request("GET", path, headers, params={"per_page": per_page})
        return [_normalize_repo(r) for r in data]

    async def _get_pr(self, args: dict, headers: dict) -> dict:
        owner, repo, number = args["owner"], args["repo"], args["number"]
        data = await _gh_request("GET", f"/repos/{owner}/{repo}/pulls/{number}", headers)
        return _normalize_pr(data)

    async def _list_prs(self, args: dict, headers: dict) -> list[dict]:
        owner, repo = args["owner"], args["repo"]
        state = args.get("state", "open")
        per_page = args.get("per_page", 30)
        data = await _gh_request(
            "GET", f"/repos/{owner}/{repo}/pulls", headers,
            params={"state": state, "per_page": per_page},
        )
        return [_normalize_pr(pr) for pr in data]

    async def _get_issue(self, args: dict, headers: dict) -> dict:
        owner, repo, number = args["owner"], args["repo"], args["number"]
        data = await _gh_request("GET", f"/repos/{owner}/{repo}/issues/{number}", headers)
        return _normalize_issue(data)

    async def _list_issues(self, args: dict, headers: dict) -> list[dict]:
        owner, repo = args["owner"], args["repo"]
        state = args.get("state", "open")
        per_page = args.get("per_page", 30)
        data = await _gh_request(
            "GET", f"/repos/{owner}/{repo}/issues", headers,
            params={"state": state, "per_page": per_page},
        )
        # GitHub issues endpoint returns both issues and PRs; filter to issues only
        return [_normalize_issue(i) for i in data if "pull_request" not in i]

    async def _get_file_contents(self, args: dict, headers: dict) -> dict:
        owner, repo, path = args["owner"], args["repo"], args["path"]
        params = {}
        if ref := args.get("ref"):
            params["ref"] = ref
        data = await _gh_request(
            "GET", f"/repos/{owner}/{repo}/contents/{path}", headers, params=params or None
        )
        return _normalize_file(data)
