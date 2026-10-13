"""Stateless MCP tools share REST/admin identity services and request context."""

import json
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent

from cmh import __version__
from cmh.auth.context import current_context, current_service
from cmh.policy.evaluator import deny


def build_mcp(settings, memory_service=None) -> FastMCP:
    base = urlsplit(settings.public_url)
    hosts = {base.hostname, "127.0.0.1", "localhost"}
    hosts.update(filter(None, (part.strip() for part in settings.allowed_hosts.split(","))))
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        # The pinned SDK's :* pattern requires an explicit port. Also allow
        # the exact hostname used by standard HTTP/HTTPS Host headers.
        allowed_hosts=[entry for host in sorted(hosts) for entry in (host, f"{host}:*")],
        allowed_origins=[settings.public_url],
    )
    server = FastMCP(
        "cmh", streamable_http_path="/mcp", json_response=True, stateless_http=True,
        transport_security=security,
    )

    @server.tool()
    def cmh_ping() -> dict:
        """Return server metadata for the authenticated request."""
        identity = current_context.get()
        if identity is None:
            raise PermissionError("Authenticated request context required")
        current_service.get().whoami(identity)
        return {
            "server": "cmh", "version": __version__,
            "principal": identity.principal["slug"], "env": settings.env,
        }

    def tool_result(body):
        return CallToolResult(
            isError=body.get("outcome") == "DENY",
            content=[TextContent(type="text", text=json.dumps(body, default=str))],
        )

    @server.tool()
    def cmh_whoami() -> CallToolResult:
        """Report caller claims without secrets; no caller-supplied identity."""
        return tool_result(current_service.get().whoami(current_context.get()))

    @server.tool()
    def cmh_check_access(operation: str, namespace: str | None = None) -> CallToolResult:
        """Dry-run the Phase 1 permission pipeline and audit its decision."""
        return tool_result(current_service.get().check(current_context.get(), operation, namespace))

    @server.tool()
    def cmh_register_agent(
        kind: str = "agent", slug: str = "", display_name: str = "", tier: int = 2,
        sponsor_id: str | None = None, template: str = "", credential_name: str = "",
    ) -> CallToolResult:
        """Registration uses JSON admin; MCP callers cannot create principals."""
        context, service = current_context.get(), current_service.get()
        decision = deny("PRINCIPAL_CREATION_FORBIDDEN", 6) if (
            context.principal["kind"] != "human"
        ) else deny("AI_CLIENT_CEILING", 2)
        return tool_result(service.record(context, decision, "principals.admin"))

    if memory_service:
        from cmh.mcp.memory import register_memory_tools

        register_memory_tools(server, memory_service)
    return server
