"""API key authentication middleware.

Resolves X-API-Key → actor + role and stores in request.state so downstream
handlers and the orchestrator can use them without re-reading the header.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Attach actor / actor_role to request.state from the X-API-Key header.

    If no key is present the request is allowed through with state values unset
    (anonymous access).  The security gateway falls back to the ACTOR_ROLES
    settings map at evaluation time.
    """

    async def dispatch(self, request: Request, call_next):
        from mcp_gateway.config import settings

        api_key = request.headers.get("X-API-Key")
        if api_key:
            key_info = settings.api_keys.get(api_key)
            if key_info:
                request.state.actor = key_info.get("actor", "api-user")
                request.state.actor_role = key_info.get("role", "viewer")
            else:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid API key"},
                )
        else:
            # Anonymous — state values left as None; endpoints use their own defaults
            request.state.actor = None
            request.state.actor_role = None

        return await call_next(request)
