"""Phase 0 transport and ping; no identity can be supplied by tool arguments."""

from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from cmh import __version__
from cmh.auth.bootstrap import principal


def build_mcp(settings) -> FastMCP:
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
        identity = principal.get()
        if identity != "bootstrap":
            raise PermissionError("Authenticated request context required")
        return {
            "server": "cmh", "version": __version__, "principal": identity, "env": settings.env,
        }

    return server
