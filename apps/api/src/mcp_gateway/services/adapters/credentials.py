"""Credential resolution — maps auth_config to HTTP headers.

Never stores raw tokens; only reads references to environment variable names.
"""

import os

from mcp_gateway.models.registry import AuthType, McpServer


class CredentialResolutionError(Exception):
    """Raised when credentials cannot be resolved (misconfiguration, missing env var)."""


def resolve_credentials(server: McpServer) -> dict[str, str]:
    """Resolve server auth_config into HTTP headers.

    If auth_config.token_env_var is set, the token is always resolved regardless
    of auth_type — auth_type=NONE only means no-auth when token_env_var is absent.

    Supported auth_config schemas:
      {"token_env_var": "GITHUB_TOKEN"}
      {"token_env_var": "X", "header_name": "Authorization", "header_prefix": "Bearer"}
      {} -> returns {} (truly no auth)
    """
    cfg = server.auth_config or {}
    env_var = cfg.get("token_env_var")

    if not env_var:
        # No token configured — treat as no-auth (e.g. public endpoints)
        return {}

    token = os.environ.get(env_var)
    if not token:
        raise CredentialResolutionError(
            f"Environment variable '{env_var}' is not set or empty "
            f"(required by server '{server.name}')"
        )

    header_name: str = cfg.get("header_name", "Authorization")
    header_prefix: str = cfg.get("header_prefix", "Bearer")
    return {header_name: f"{header_prefix} {token}"}
