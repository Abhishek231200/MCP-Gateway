"""GitHub adapter — wraps GitHub REST API v3."""

from typing import Any

import httpx
import structlog

from mcp_gateway.models.registry import McpServer
from mcp_gateway.services.adapters.base import AdapterError, BaseAdapter

logger = structlog.get_logger()

GITHUB_API_BASE = "https://api.github.com"
_TIMEOUT = 15.0

_TOOL_DEFINITIONS = [
    {
        "tool_name": "list_repos",
        "description": "List repositories for a GitHub user, org, or the authenticated user",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "GitHub username to list repos for"},
                "org": {"type": "string", "description": "Organization name (overrides owner)"},
                "per_page": {"type": "integer", "default": 100, "maximum": 100},
            },
        },
        "output_schema": {"type": "array"},
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
        "output_schema": {"type": "array"},
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
                "labels": {"type": "string", "description": "Comma-separated label names to filter by"},
                "per_page": {"type": "integer", "default": 30, "maximum": 100},
            },
            "required": ["owner", "repo"],
        },
        "output_schema": {"type": "array"},
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
                "ref": {"type": "string", "description": "Branch, tag, or commit SHA"},
            },
            "required": ["owner", "repo", "path"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "read",
    },
    {
        "tool_name": "list_commits",
        "description": "List commits on a repository branch",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "sha": {"type": "string", "description": "Branch name or commit SHA (default: default branch)"},
                "per_page": {"type": "integer", "default": 20, "maximum": 100},
                "author": {"type": "string", "description": "Filter by author login"},
            },
            "required": ["owner", "repo"],
        },
        "output_schema": {"type": "array"},
        "required_permission": "read",
    },
    {
        "tool_name": "get_commit",
        "description": "Get details and file changes for a specific commit",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "sha": {"type": "string", "description": "Commit SHA"},
            },
            "required": ["owner", "repo", "sha"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "read",
    },
    {
        "tool_name": "search_code",
        "description": "Search code across GitHub repositories",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'rate_limit repo:owner/repo')"},
                "per_page": {"type": "integer", "default": 10, "maximum": 30},
            },
            "required": ["query"],
        },
        "output_schema": {"type": "array"},
        "required_permission": "read",
    },
    {
        "tool_name": "create_issue",
        "description": "Create a new issue in a repository",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "assignees": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["owner", "repo", "title"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "write",
    },
    {
        "tool_name": "close_issue",
        "description": "Close an open issue",
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
        "required_permission": "write",
    },
    {
        "tool_name": "comment_on_pr",
        "description": "Post a review comment on a pull request",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "number": {"type": "integer", "description": "PR number"},
                "body": {"type": "string", "description": "Comment text (supports markdown)"},
            },
            "required": ["owner", "repo", "number", "body"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "write",
    },
    {
        "tool_name": "create_branch",
        "description": "Create a new branch from a base ref",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "branch": {"type": "string", "description": "Name for the new branch"},
                "from_branch": {"type": "string", "description": "Base branch to branch from (default: default branch)"},
            },
            "required": ["owner", "repo", "branch"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "write",
    },
    {
        "tool_name": "get_repo_stats",
        "description": "Get repository statistics: contributors, languages, commit activity",
        "input_schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
            },
            "required": ["owner", "repo"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "read",
    },
]


def _normalize_repo(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r.get("id"),
        "name": r.get("name"),
        "full_name": r.get("full_name"),
        "description": r.get("description"),
        "url": r.get("html_url"),
        "private": r.get("private"),
        "default_branch": r.get("default_branch"),
        "stars": r.get("stargazers_count"),
        "forks": r.get("forks_count"),
        "open_issues": r.get("open_issues_count"),
        "language": r.get("language"),
        "updated_at": r.get("updated_at"),
        "topics": r.get("topics", []),
    }


def _normalize_pr(pr: dict[str, Any]) -> dict[str, Any]:
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
        "mergeable": pr.get("mergeable"),
        "labels": [lb.get("name") for lb in (pr.get("labels") or [])],
        "reviewers": [(r.get("login")) for r in (pr.get("requested_reviewers") or [])],
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
        "merged_at": pr.get("merged_at"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "changed_files": pr.get("changed_files"),
    }


def _normalize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "url": issue.get("html_url"),
        "author": (issue.get("user") or {}).get("login"),
        "body": issue.get("body"),
        "labels": [lb.get("name") for lb in (issue.get("labels") or [])],
        "assignees": [(a.get("login")) for a in (issue.get("assignees") or [])],
        "comments": issue.get("comments"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"),
    }


def _normalize_commit(c: dict[str, Any]) -> dict[str, Any]:
    commit = c.get("commit") or {}
    author = commit.get("author") or {}
    return {
        "sha": c.get("sha"),
        "message": commit.get("message", "").split("\n")[0],
        "author": author.get("name"),
        "author_email": author.get("email"),
        "date": author.get("date"),
        "url": c.get("html_url"),
        "files_changed": len(c.get("files") or []),
    }


def _normalize_file(f: dict[str, Any]) -> dict[str, Any]:
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
    }


async def _gh_request(
    method: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> Any:
    default_headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    merged = {**default_headers, **headers}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.request(
            method, f"{GITHUB_API_BASE}{path}",
            headers=merged, params=params, json=json,
        )
    if resp.status_code == 204:
        return {}
    if resp.status_code >= 400:
        raise AdapterError(
            f"GitHub API returned {resp.status_code}: {resp.text[:300]}",
            status_code=resp.status_code,
        )
    return resp.json()


class GitHubAdapter(BaseAdapter):
    @property
    def adapter_type(self) -> str:
        return "github"

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        return _TOOL_DEFINITIONS

    async def _execute_tool(
        self,
        server: McpServer,
        tool_name: str,
        arguments: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        match tool_name:
            case "list_repos":      return await self._list_repos(arguments, headers)
            case "get_pr":          return await self._get_pr(arguments, headers)
            case "list_prs":        return await self._list_prs(arguments, headers)
            case "get_issue":       return await self._get_issue(arguments, headers)
            case "list_issues":     return await self._list_issues(arguments, headers)
            case "get_file_contents": return await self._get_file_contents(arguments, headers)
            case "list_commits":    return await self._list_commits(arguments, headers)
            case "get_commit":      return await self._get_commit(arguments, headers)
            case "search_code":     return await self._search_code(arguments, headers)
            case "create_issue":    return await self._create_issue(arguments, headers)
            case "close_issue":     return await self._close_issue(arguments, headers)
            case "comment_on_pr":   return await self._comment_on_pr(arguments, headers)
            case "create_branch":   return await self._create_branch(arguments, headers)
            case "get_repo_stats":  return await self._get_repo_stats(arguments, headers)
            case _:
                raise AdapterError(f"Unknown tool '{tool_name}' for GitHub adapter")

    @staticmethod
    def _require(args: dict[str, Any], *keys: str) -> None:
        missing = [k for k in keys if k not in args or args[k] is None]
        if missing:
            raise AdapterError(
                f"Missing required argument(s): {', '.join(missing)}. "
                f"These must be provided explicitly — they cannot be inferred from prior steps."
            )

    async def _list_repos(self, args: dict[str, Any], headers: dict[str, str]) -> list[dict[str, Any]]:
        org = args.get("org")
        owner = args.get("owner") or args.get("username") or args.get("user")
        per_page = min(args.get("per_page", 100), 100)
        params = {"per_page": per_page, "sort": "updated", "direction": "desc"}
        if org:
            path = f"/orgs/{org}/repos"
        elif owner:
            path = f"/users/{owner}/repos"
        else:
            path = "/user/repos"
        data = await _gh_request("GET", path, headers, params=params)
        return [_normalize_repo(r) for r in data]

    async def _get_pr(self, args: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self._require(args, "owner", "repo", "number")
        data = await _gh_request("GET", f"/repos/{args['owner']}/{args['repo']}/pulls/{args['number']}", headers)
        return _normalize_pr(data)

    async def _list_prs(self, args: dict[str, Any], headers: dict[str, str]) -> list[dict[str, Any]]:
        self._require(args, "owner", "repo")
        params = {"state": args.get("state", "open"), "per_page": args.get("per_page", 30)}
        data = await _gh_request("GET", f"/repos/{args['owner']}/{args['repo']}/pulls", headers, params=params)
        return [_normalize_pr(pr) for pr in data]

    async def _get_issue(self, args: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self._require(args, "owner", "repo", "number")
        data = await _gh_request("GET", f"/repos/{args['owner']}/{args['repo']}/issues/{args['number']}", headers)
        return _normalize_issue(data)

    async def _list_issues(self, args: dict[str, Any], headers: dict[str, str]) -> list[dict[str, Any]]:
        self._require(args, "owner", "repo")
        params: dict[str, Any] = {"state": args.get("state", "open"), "per_page": args.get("per_page", 30)}
        if labels := args.get("labels"):
            params["labels"] = labels
        data = await _gh_request("GET", f"/repos/{args['owner']}/{args['repo']}/issues", headers, params=params)
        return [_normalize_issue(i) for i in data if "pull_request" not in i]

    async def _get_file_contents(self, args: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self._require(args, "owner", "repo", "path")
        params = {"ref": args["ref"]} if args.get("ref") else None
        data = await _gh_request("GET", f"/repos/{args['owner']}/{args['repo']}/contents/{args['path']}", headers, params=params)
        return _normalize_file(data)

    async def _list_commits(self, args: dict[str, Any], headers: dict[str, str]) -> list[dict[str, Any]]:
        self._require(args, "owner", "repo")
        params: dict[str, Any] = {"per_page": args.get("per_page", 20)}
        if sha := args.get("sha"):
            params["sha"] = sha
        if author := args.get("author"):
            params["author"] = author
        data = await _gh_request("GET", f"/repos/{args['owner']}/{args['repo']}/commits", headers, params=params)
        return [_normalize_commit(c) for c in data]

    async def _get_commit(self, args: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self._require(args, "owner", "repo", "sha")
        data = await _gh_request("GET", f"/repos/{args['owner']}/{args['repo']}/commits/{args['sha']}", headers)
        result = _normalize_commit(data)
        result["files"] = [
            {"filename": f.get("filename"), "status": f.get("status"),
             "additions": f.get("additions"), "deletions": f.get("deletions")}
            for f in (data.get("files") or [])[:20]
        ]
        return result

    async def _search_code(self, args: dict[str, Any], headers: dict[str, str]) -> list[dict[str, Any]]:
        self._require(args, "query")
        params = {"q": args["query"], "per_page": args.get("per_page", 10)}
        data = await _gh_request("GET", "/search/code", headers, params=params)
        return [
            {
                "name": item.get("name"),
                "path": item.get("path"),
                "url": item.get("html_url"),
                "repo": (item.get("repository") or {}).get("full_name"),
                "sha": item.get("sha"),
            }
            for item in (data.get("items") or [])
        ]

    async def _create_issue(self, args: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self._require(args, "owner", "repo", "title")
        body: dict[str, Any] = {"title": args["title"]}
        if desc := args.get("body"):
            body["body"] = desc
        if labels := args.get("labels"):
            body["labels"] = labels
        if assignees := args.get("assignees"):
            body["assignees"] = assignees
        data = await _gh_request("POST", f"/repos/{args['owner']}/{args['repo']}/issues", headers, json=body)
        return _normalize_issue(data)

    async def _close_issue(self, args: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self._require(args, "owner", "repo", "number")
        data = await _gh_request(
            "PATCH", f"/repos/{args['owner']}/{args['repo']}/issues/{args['number']}",
            headers, json={"state": "closed"},
        )
        return _normalize_issue(data)

    async def _comment_on_pr(self, args: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self._require(args, "owner", "repo", "number", "body")
        data = await _gh_request(
            "POST", f"/repos/{args['owner']}/{args['repo']}/issues/{args['number']}/comments",
            headers, json={"body": args["body"]},
        )
        return {
            "id": data.get("id"),
            "url": data.get("html_url"),
            "body": data.get("body"),
            "author": (data.get("user") or {}).get("login"),
            "created_at": data.get("created_at"),
        }

    async def _create_branch(self, args: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self._require(args, "owner", "repo", "branch")
        owner, repo = args["owner"], args["repo"]
        from_branch = args.get("from_branch")

        # Resolve the SHA of the base branch
        if from_branch:
            ref_data = await _gh_request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{from_branch}", headers)
        else:
            repo_data = await _gh_request("GET", f"/repos/{owner}/{repo}", headers)
            default_branch = repo_data.get("default_branch", "main")
            ref_data = await _gh_request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{default_branch}", headers)

        sha = (ref_data.get("object") or {}).get("sha")
        data = await _gh_request(
            "POST", f"/repos/{owner}/{repo}/git/refs",
            headers, json={"ref": f"refs/heads/{args['branch']}", "sha": sha},
        )
        return {
            "branch": args["branch"],
            "sha": (data.get("object") or {}).get("sha"),
            "url": data.get("url"),
        }

    async def _get_repo_stats(self, args: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        self._require(args, "owner", "repo")
        owner, repo = args["owner"], args["repo"]
        repo_data = await _gh_request("GET", f"/repos/{owner}/{repo}", headers)
        languages = await _gh_request("GET", f"/repos/{owner}/{repo}/languages", headers)
        return {
            "name": repo_data.get("full_name"),
            "stars": repo_data.get("stargazers_count"),
            "forks": repo_data.get("forks_count"),
            "open_issues": repo_data.get("open_issues_count"),
            "watchers": repo_data.get("watchers_count"),
            "size_kb": repo_data.get("size"),
            "languages": languages,
            "license": (repo_data.get("license") or {}).get("name"),
            "created_at": repo_data.get("created_at"),
            "updated_at": repo_data.get("updated_at"),
        }
