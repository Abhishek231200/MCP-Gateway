"""Auth middleware — resolves identity from JWT Bearer token or X-API-Key header."""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

_PUBLIC_PATHS = {"/health", "/auth/request-otp", "/auth/verify-otp", "/docs", "/redoc", "/openapi.json"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Resolve actor + role from:
      1. Authorization: Bearer <jwt>  — issued by /auth/verify-otp
      2. X-API-Key: <key>             — static keys from settings.api_keys
      3. Anonymous                    — state values are None (public endpoints only)
    """

    async def dispatch(self, request: Request, call_next):
        from mcp_gateway.config import settings

        # Always allow public paths without auth
        if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/auth/"):
            request.state.actor = None
            request.state.actor_role = None
            request.state.jwt_user = None
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        api_key = request.headers.get("X-API-Key")

        if auth_header.startswith("Bearer "):
            try:
                import jwt
                payload = jwt.decode(
                    auth_header[7:],
                    settings.secret_key,
                    algorithms=["HS256"],
                )
                request.state.actor = payload.get("name", payload.get("email", "user"))
                request.state.actor_role = payload.get("role", "viewer")
                request.state.jwt_user = payload
            except jwt.ExpiredSignatureError:
                return JSONResponse(status_code=401, content={"detail": "Token expired"})
            except jwt.InvalidTokenError:
                return JSONResponse(status_code=401, content={"detail": "Invalid token"})

        elif api_key:
            key_info = settings.api_keys.get(api_key)
            if key_info:
                request.state.actor = key_info.get("actor", "api-user")
                request.state.actor_role = key_info.get("role", "viewer")
                request.state.jwt_user = None
            else:
                return JSONResponse(status_code=401, content={"detail": "Invalid API key"})

        else:
            request.state.actor = None
            request.state.actor_role = None
            request.state.jwt_user = None

        return await call_next(request)
