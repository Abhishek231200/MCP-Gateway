"""Knowledge Base (RAG) adapter — wraps any REST-compliant vector-store endpoint.

The server's base_url must expose:
  POST /query        — full RAG: retrieve + generate answer via Claude
  POST /search       — semantic search, body: {query, top_k, min_score}
  POST /documents    — add document, body: {content, title?, metadata?}
  GET  /documents    — list documents, params: limit, offset
  DELETE /documents/{id} — remove a document
"""

from typing import Any

import httpx
import structlog

from mcp_gateway.models.registry import McpServer
from mcp_gateway.services.adapters.base import AdapterError, BaseAdapter

logger = structlog.get_logger()

_TIMEOUT = 15.0

_TOOL_DEFINITIONS = [
    {
        "tool_name": "query",
        "description": "Full RAG pipeline: retrieve relevant documents and generate a grounded answer via Claude",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Natural-language question to answer"},
                "top_k": {"type": "integer", "default": 5, "maximum": 20},
                "min_score": {
                    "type": "number",
                    "default": 0.1,
                    "description": "Minimum similarity score for retrieved chunks (0–1)",
                },
            },
            "required": ["question"],
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "sources": {"type": "array"},
                "question": {"type": "string"},
            },
        },
        "required_permission": "read",
    },
    {
        "tool_name": "search",
        "description": "Semantic search over the knowledge base; returns the top-k most relevant document chunks",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query"},
                "top_k": {"type": "integer", "default": 5, "maximum": 20},
                "min_score": {
                    "type": "number",
                    "default": 0.0,
                    "description": "Minimum similarity score threshold (0–1)",
                },
            },
            "required": ["query"],
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
    {
        "tool_name": "add_document",
        "description": "Add a document to the knowledge base for indexing",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Text content of the document"},
                "title": {"type": "string", "description": "Document title"},
                "metadata": {
                    "type": "object",
                    "description": "Arbitrary key-value metadata attached to the document",
                },
            },
            "required": ["content"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "write",
    },
    {
        "tool_name": "list_documents",
        "description": "List documents indexed in the knowledge base",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50, "maximum": 200},
                "offset": {"type": "integer", "default": 0},
            },
        },
        "output_schema": {"type": "array", "items": {"type": "object"}},
        "required_permission": "read",
    },
    {
        "tool_name": "delete_document",
        "description": "Remove a document from the knowledge base by ID",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "Document ID to delete"},
            },
            "required": ["document_id"],
        },
        "output_schema": {"type": "object"},
        "required_permission": "admin",
    },
]


async def _kb_request(
    method: str,
    base_url: str,
    path: str,
    headers: dict[str, str],
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.request(method, url, headers=headers, json=json, params=params)
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:200]
        raise AdapterError(
            f"Knowledge Base API returned {resp.status_code}: {detail}",
            status_code=resp.status_code,
        )
    if resp.status_code == 204:
        return {}
    return resp.json()


class KnowledgeBaseAdapter(BaseAdapter):
    @property
    def adapter_type(self) -> str:
        return "kb"

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        return _TOOL_DEFINITIONS

    async def _execute_tool(
        self,
        server: McpServer,
        tool_name: str,
        arguments: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        base_url = server.base_url
        match tool_name:
            case "query":
                return await self._query(base_url, arguments, headers)
            case "search":
                return await self._search(base_url, arguments, headers)
            case "add_document":
                return await self._add_document(base_url, arguments, headers)
            case "list_documents":
                return await self._list_documents(base_url, arguments, headers)
            case "delete_document":
                return await self._delete_document(base_url, arguments, headers)
            case _:
                raise AdapterError(f"Unknown tool '{tool_name}' for Knowledge Base adapter")

    async def _query(
        self, base_url: str, args: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        body = {
            "question": args["question"],
            "top_k": args.get("top_k", 5),
            "min_score": args.get("min_score", 0.1),
        }
        result = await _kb_request("POST", base_url, "/query", headers, json=body)
        return result if isinstance(result, dict) else {"answer": result}

    async def _search(
        self, base_url: str, args: dict[str, Any], headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        body = {
            "query": args["query"],
            "top_k": args.get("top_k", 5),
            "min_score": args.get("min_score", 0.0),
        }
        data = await _kb_request("POST", base_url, "/search", headers, json=body)
        return data if isinstance(data, list) else data.get("results", [])

    async def _add_document(
        self, base_url: str, args: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"content": args["content"]}
        if title := args.get("title"):
            body["title"] = title
        if metadata := args.get("metadata"):
            body["metadata"] = metadata
        result = await _kb_request("POST", base_url, "/documents", headers, json=body)
        return result if isinstance(result, dict) else {"result": result}

    async def _list_documents(
        self, base_url: str, args: dict[str, Any], headers: dict[str, str]
    ) -> list[dict[str, Any]]:
        params = {"limit": args.get("limit", 50), "offset": args.get("offset", 0)}
        data = await _kb_request("GET", base_url, "/documents", headers, params=params)
        return data if isinstance(data, list) else data.get("documents", [])

    async def _delete_document(
        self, base_url: str, args: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        doc_id = args["document_id"]
        result = await _kb_request("DELETE", base_url, f"/documents/{doc_id}", headers)
        return result if isinstance(result, dict) else {}
