"""SecurityGateway — evaluates tool calls against OPA authorization policies."""

from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class PolicyDecision:
    allow: bool
    reason: str
    actor_role: str


class SecurityGateway:
    """Calls the OPA REST API to evaluate tool-call authorization."""

    def __init__(self, opa_url: str, actor_roles: dict[str, str]) -> None:
        self._opa_url = opa_url.rstrip("/")
        self._actor_roles = actor_roles

    def resolve_role(self, actor: str) -> str:
        """Return the actor's role, defaulting to 'viewer' if not configured."""
        return self._actor_roles.get(actor, "viewer")

    async def evaluate(
        self,
        actor: str,
        server_name: str,
        tool_name: str,
        required_permission: str,
    ) -> PolicyDecision:
        """Evaluate an authorization decision for a tool call.

        Returns a PolicyDecision with allow=False if OPA is unreachable (fail-closed).
        """
        actor_role = self.resolve_role(actor)
        input_doc = {
            "input": {
                "actor": actor,
                "actor_role": actor_role,
                "server_name": server_name,
                "tool_name": tool_name,
                "required_permission": required_permission,
            }
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self._opa_url}/v1/data/authz",
                    json=input_doc,
                )
                resp.raise_for_status()
                result = resp.json().get("result", {})
                return PolicyDecision(
                    allow=result.get("allow", False),
                    reason=result.get("reason", "Policy evaluated with no reason"),
                    actor_role=actor_role,
                )
        except Exception as exc:
            logger.warning(
                "security_gateway.opa_unreachable",
                error=str(exc),
                opa_url=self._opa_url,
            )
            # Fail closed: deny if OPA is unreachable
            return PolicyDecision(
                allow=False,
                reason=f"Policy engine unreachable — denying by default: {exc}",
                actor_role=actor_role,
            )


def get_security_gateway() -> SecurityGateway:
    from mcp_gateway.config import settings

    return SecurityGateway(
        opa_url=settings.opa_url,
        actor_roles=settings.actor_roles,
    )
