"""Google Drive adapter — wraps Google Drive API v3."""

from typing import Any

import httpx
import structlog

from mcp_gateway.models.registry import McpServer
from mcp_gateway.services.adapters.base import AdapterError, BaseAdapter

logger = structlog.get_logger()

GDRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
_TIMEOUT = 15.0

_FILE_FIELDS = "id,name,mimeType,size,modifiedTime,createdTime,webViewLink,parents,shared,trashed"

_TOOL_DEFINITIONS = [
    {
        "tool_name": "list_files",
        "description": "List files and folders in Google Drive",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_size": {"type": "integer", "default": 20, "maximum": 100},
                "order_by": {
                    "type": "string",
                    "default": "modifiedTime desc",
                    "description": "Sort order (e.g. 'name', 'modifiedTime desc')",
                },
                "include_trashed": {"type": "boolean", "default": False},
            },
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
    {
        "tool_name": "get_file_metadata",
        "description": "Get metadata for a specific file or folder by ID",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Google Drive file/folder ID"},
            },
            "required": ["file_id"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "read",
    },
    {
        "tool_name": "download_file",
        "description": "Download the text content of a file (plain text or exported Google Doc)",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Google Drive file ID"},
                "mime_type": {
                    "type": "string",
                    "description": "Export MIME type for Google Workspace docs (e.g. 'text/plain'). Omit for binary files.",
                },
            },
            "required": ["file_id"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "read",
    },
    {
        "tool_name": "search_files",
        "description": "Search for files in Google Drive using Drive query syntax",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Drive query string (e.g. \"name contains 'report'\" or \"mimeType='application/pdf'\")",
                },
                "page_size": {"type": "integer", "default": 20, "maximum": 100},
            },
            "required": ["query"],
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
    {
        "tool_name": "list_shared_drives",
        "description": "List shared drives (Team Drives) accessible to the authenticated user",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_size": {"type": "integer", "default": 10, "maximum": 100},
            },
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
]


def _normalize_file(f: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "mime_type": f.get("mimeType"),
        "size": f.get("size"),
        "modified_time": f.get("modifiedTime"),
        "created_time": f.get("createdTime"),
        "web_view_link": f.get("webViewLink"),
        "parents": f.get("parents", []),
        "shared": f.get("shared"),
        "trashed": f.get("trashed"),
    }


def _normalize_drive(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d.get("id"),
        "name": d.get("name"),
        "kind": d.get("kind"),
        "created_time": d.get("createdTime"),
    }


async def _gdrive_request(
    method: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
) -> Any:
    url = f"{GDRIVE_API_BASE}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.request(method, url, headers=headers, params=params)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        raise AdapterError(
            f"Google Drive API returned {resp.status_code}: {detail}",
            status_code=resp.status_code,
        )
    return resp.json()


async def _gdrive_download(
    file_id: str,
    headers: dict[str, str],
    export_mime: str | None = None,
) -> str:
    if export_mime:
        url = f"{GDRIVE_API_BASE}/files/{file_id}/export"
        params: dict[str, Any] = {"mimeType": export_mime}
    else:
        url = f"{GDRIVE_API_BASE}/files/{file_id}"
        params = {"alt": "media"}

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code >= 400:
        raise AdapterError(
            f"Google Drive download returned {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
        )
    return resp.text


class GoogleDriveAdapter(BaseAdapter):
    @property
    def adapter_type(self) -> str:
        return "gdrive"

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
            case "list_files":
                return await self._list_files(arguments, headers)
            case "get_file_metadata":
                return await self._get_file_metadata(arguments, headers)
            case "download_file":
                return await self._download_file(arguments, headers)
            case "search_files":
                return await self._search_files(arguments, headers)
            case "list_shared_drives":
                return await self._list_shared_drives(arguments, headers)
            case _:
                raise AdapterError(f"Unknown tool '{tool_name}' for Google Drive adapter")

    async def _list_files(
        self, args: dict[str, Any], headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "pageSize": args.get("page_size", 20),
            "orderBy": args.get("order_by", "modifiedTime desc"),
            "fields": f"files({_FILE_FIELDS})",
        }
        if not args.get("include_trashed", False):
            params["q"] = "trashed=false"
        data = await _gdrive_request("GET", "/files", headers, params)
        return [_normalize_file(f) for f in data.get("files", [])]

    async def _get_file_metadata(
        self, args: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        file_id = args["file_id"]
        data = await _gdrive_request(
            "GET", f"/files/{file_id}", headers, {"fields": _FILE_FIELDS}
        )
        return _normalize_file(data)

    async def _download_file(
        self, args: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        file_id = args["file_id"]
        export_mime = args.get("mime_type")
        meta = await _gdrive_request(
            "GET", f"/files/{file_id}", headers, {"fields": "id,name,mimeType"}
        )
        content = await _gdrive_download(file_id, headers, export_mime)
        return {
            "id": meta.get("id"),
            "name": meta.get("name"),
            "mime_type": meta.get("mimeType"),
            "content": content,
        }

    async def _search_files(
        self, args: dict[str, Any], headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "q": args["query"],
            "pageSize": args.get("page_size", 20),
            "fields": f"files({_FILE_FIELDS})",
        }
        data = await _gdrive_request("GET", "/files", headers, params)
        return [_normalize_file(f) for f in data.get("files", [])]

    async def _list_shared_drives(
        self, args: dict[str, Any], headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"pageSize": args.get("page_size", 10)}
        data = await _gdrive_request("GET", "/drives", headers, params)
        return [_normalize_drive(d) for d in data.get("drives", [])]
