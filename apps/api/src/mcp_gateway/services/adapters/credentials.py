"""Credential resolution — maps auth_config to HTTP headers.

Never stores raw tokens; only reads references to environment variable names.
"""

import os

from mcp_gateway.models.registry import AuthType, McpServer


class CredentialResolutionError(Exception):
    """Raised when credentials cannot be resolved (misconfiguration, missing env var)."""


def resolve_credentials(server: McpServer) -> dict[str, str]:
    """Resolve server auth_config into HTTP headers.

    Supported auth_config schemas:
      API_KEY / OAUTH2 / JWT:
        {"token_env_var": "GITHUB_TOKEN"}
        {"token_env_var": "X", "header_name": "Authorization", "header_prefix": "Bearer"}
      NONE: {} -> returns {}
    """
    if server.auth_type == AuthType.NONE:
        return {}

    cfg = server.auth_config or {}
    env_var = cfg.get("token_env_var")
    if not env_var:
        raise CredentialResolutionError(
            f"Server '{server.name}' has auth_type={server.auth_type} "
            f"but auth_config.token_env_var is not set"
        )

    token = os.environ.get(env_var)
    if not token:
        raise CredentialResolutionError(
            f"Environment variable '{env_var}' is not set or empty "
            f"(required by server '{server.name}')"
        )

    header_name: str = cfg.get("header_name", "Authorization")
    header_prefix: str = cfg.get("header_prefix", "Bearer")
    return {header_name: f"{header_prefix} {token}"}
