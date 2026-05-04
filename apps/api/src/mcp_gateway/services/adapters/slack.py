"""Slack adapter — wraps Slack Web API."""

from typing import Any

import httpx
import structlog

from mcp_gateway.models.registry import McpServer
from mcp_gateway.services.adapters.base import AdapterError, BaseAdapter

logger = structlog.get_logger()

SLACK_API_BASE = "https://slack.com/api"
_TIMEOUT = 10.0

_TOOL_DEFINITIONS = [
    {
        "tool_name": "list_channels",
        "description": "List channels in the Slack workspace the bot can access",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 100, "maximum": 200},
                "exclude_archived": {"type": "boolean", "default": True},
                "types": {
                    "type": "string",
                    "default": "public_channel",
                    "description": "Comma-separated channel types: public_channel, private_channel, mpim, im",
                },
            },
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
    {
        "tool_name": "get_channel_history",
        "description": "Fetch the message history for a Slack channel",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel ID (e.g. C01234ABC)"},
                "limit": {"type": "integer", "default": 50, "maximum": 200},
                "oldest": {"type": "string", "description": "Start of time range (Unix timestamp as string)"},
                "latest": {"type": "string", "description": "End of time range (Unix timestamp as string)"},
            },
            "required": ["channel"],
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
    {
        "tool_name": "post_message",
        "description": "Post a message to a Slack channel or DM",
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel ID or name"},
                "text": {"type": "string", "description": "Message text (supports mrkdwn)"},
                "thread_ts": {
                    "type": "string",
                    "description": "Timestamp of parent message to reply in-thread",
                },
            },
            "required": ["channel", "text"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "write",
    },
    {
        "tool_name": "get_user_info",
        "description": "Get profile information for a Slack user",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "Slack user ID (e.g. U012AB3CD)"},
            },
            "required": ["user_id"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "read",
    },
    {
        "tool_name": "search_messages",
        "description": "Search messages across the workspace (requires user token with search:read scope)",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string"},
                "count": {"type": "integer", "default": 20, "maximum": 100},
                "sort": {
                    "type": "string",
                    "enum": ["score", "timestamp"],
                    "default": "score",
                },
            },
            "required": ["query"],
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
]


def _normalize_channel(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "is_private": c.get("is_private"),
        "is_archived": c.get("is_archived"),
        "member_count": c.get("num_members"),
        "topic": (c.get("topic") or {}).get("value"),
        "purpose": (c.get("purpose") or {}).get("value"),
        "created": c.get("created"),
    }


def _normalize_message(m: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": m.get("type"),
        "ts": m.get("ts"),
        "user": m.get("user"),
        "bot_id": m.get("bot_id"),
        "text": m.get("text"),
        "thread_ts": m.get("thread_ts"),
        "reply_count": m.get("reply_count"),
        "reactions": m.get("reactions"),
    }


def _normalize_user(u: dict[str, Any]) -> dict[str, Any]:
    profile = u.get("profile") or {}
    return {
        "id": u.get("id"),
        "name": u.get("name"),
        "real_name": u.get("real_name"),
        "display_name": profile.get("display_name"),
        "email": profile.get("email"),
        "title": profile.get("title"),
        "is_bot": u.get("is_bot"),
        "is_admin": u.get("is_admin"),
        "tz": u.get("tz"),
    }


async def _slack_request(
    method: str,
    slack_method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a Slack Web API method.

    GET → query params; POST → JSON body.
    Raises AdapterError if HTTP fails or Slack returns ok=false.
    """
    url = f"{SLACK_API_BASE}/{slack_method}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        if method == "POST":
            resp = await client.post(
                url,
                headers={**headers, "Content-Type": "application/json; charset=utf-8"},
                json=payload or {},
            )
        else:
            resp = await client.get(url, headers=headers, params=payload)

    if resp.status_code >= 400:
        raise AdapterError(
            f"Slack API returned HTTP {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
        )
    data: dict[str, Any] = resp.json()
    if not data.get("ok"):
        error = data.get("error", "unknown_error")
        raise AdapterError(f"Slack API error: {error}")
    return data


class SlackAdapter(BaseAdapter):
    @property
    def adapter_type(self) -> str:
        return "slack"

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
            case "list_channels":
                return await self._list_channels(arguments, headers)
            case "get_channel_history":
                return await self._get_channel_history(arguments, headers)
            case "post_message":
                return await self._post_message(arguments, headers)
            case "get_user_info":
                return await self._get_user_info(arguments, headers)
            case "search_messages":
                return await self._search_messages(arguments, headers)
            case _:
                raise AdapterError(f"Unknown tool '{tool_name}' for Slack adapter")

    async def _list_channels(
        self, args: dict[str, Any], headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "limit": args.get("limit", 100),
            "exclude_archived": str(args.get("exclude_archived", True)).lower(),
            "types": args.get("types", "public_channel"),
        }
        data = await _slack_request("GET", "conversations.list", headers, payload)
        return [_normalize_channel(c) for c in data.get("channels", [])]

    async def _get_channel_history(
        self, args: dict[str, Any], headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "channel": args["channel"],
            "limit": args.get("limit", 50),
        }
        if oldest := args.get("oldest"):
            payload["oldest"] = oldest
        if latest := args.get("latest"):
            payload["latest"] = latest
        data = await _slack_request("POST", "conversations.history", headers, payload)
        return [_normalize_message(m) for m in data.get("messages", [])]

    async def _post_message(
        self, args: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"channel": args["channel"], "text": args["text"]}
        if thread_ts := args.get("thread_ts"):
            payload["thread_ts"] = thread_ts
        data = await _slack_request("POST", "chat.postMessage", headers, payload)
        return {
            "ts": data.get("ts"),
            "channel": data.get("channel"),
            "message": _normalize_message(data.get("message") or {}),
        }

    async def _get_user_info(
        self, args: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        data = await _slack_request("GET", "users.info", headers, {"user": args["user_id"]})
        return _normalize_user(data.get("user") or {})

    async def _search_messages(
        self, args: dict[str, Any], headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "query": args["query"],
            "count": args.get("count", 20),
            "sort": args.get("sort", "score"),
        }
        data = await _slack_request("GET", "search.messages", headers, payload)
        matches = (data.get("messages") or {}).get("matches", [])
        return [
            {
                "ts": m.get("ts"),
                "text": m.get("text"),
                "user": m.get("username"),
                "channel": (m.get("channel") or {}).get("name"),
                "permalink": m.get("permalink"),
            }
            for m in matches
        ]
