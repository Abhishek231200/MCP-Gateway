"""Adapter dispatch — maps adapter_type strings to adapter instances."""

from mcp_gateway.models.registry import McpServer
from mcp_gateway.services.adapters.base import AdapterNotFoundError, BaseAdapter
from mcp_gateway.services.adapters.github import GitHubAdapter

_REGISTRY: dict[str, BaseAdapter] = {
    "github": GitHubAdapter(),
    # Week 4: "slack": SlackAdapter(), "gdrive": GoogleDriveAdapter(), "kb": KnowledgeBaseAdapter()
}


def get_adapter(server: McpServer) -> BaseAdapter:
    """Return the adapter for the given server based on metadata_.adapter_type."""
    adapter_type = (server.metadata_ or {}).get("adapter_type", "")
    adapter = _REGISTRY.get(adapter_type)
    if adapter is None:
        raise AdapterNotFoundError(
            f"No adapter registered for type '{adapter_type}'. "
            f"Set metadata.adapter_type on the server to one of: {list(_REGISTRY)}"
        )
    return adapter
