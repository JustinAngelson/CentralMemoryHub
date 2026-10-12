"""Authenticate before dispatch; do not forward headers into MCP tool arguments."""

import ipaddress
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from cmh.auth.authentication import bearer, cookie
from cmh.auth.context import PrincipalContext, current_context, current_service
from cmh.logging import request_id
from cmh.policy.evaluator import deny


def selected_ip(scope, headers, hops):
    peer = (scope.get("client") or ("unknown",))[0]
    values = headers.get("x-forwarded-for", "").split(",")
    if hops and len(values) >= hops:
        candidate = values[-hops].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
    return peer


class IdentityMiddleware:
    def __init__(self, app, service, settings, limits):
        self.app, self.service, self.settings, self.limits = app, service, settings, limits

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path == "/healthz" and scope["method"] == "GET":
            return await self.app(scope, receive, send)
        headers = {key.decode().lower(): value.decode() for key, value in scope["headers"]}
        meta = {
            "route": path, "surface": "mcp" if path.startswith("/mcp") else (
                "admin" if path.startswith("/admin/") else "rest"
            ),
            "client_ip": selected_ip(scope, headers, self.settings.trusted_proxy_hops),
            "request_id": request_id.get(),
        }
        context = PrincipalContext({}, request_meta=meta)
        if path.startswith("/mcp") and path != "/mcp":
            # Unknown MCP paths cannot be used to bypass the shared IP audit
            # budget. Preserve 404 without authenticating or revealing routes.
            audit, summary = self.limits.failure(meta["client_ip"], self.service.now())
            if audit:
                self.service.record(context, deny("NOT_FOUND"), "routing.not_found")
            elif summary:
                self.service.record(context, deny("RATE_LIMITED"), "auth.rate_limit_summary")
            return await JSONResponse({"code": "NOT_FOUND"}, status_code=404)(
                scope, receive, send,
            )
        rejection = None
        status = 200
        if path.startswith("/admin/api/"):
            special = path in ("/admin/api/bootstrap", "/admin/api/login")
            if not special:
                jar = SimpleCookie()
                try:
                    jar.load(headers.get("cookie", ""))
                    value = jar["cmh_session"].value if "cmh_session" in jar else None
                except CookieError:
                    value = None
                context, rejection, status = cookie(
                    self.service.engine, value, self.service.now(), meta,
                )
            if scope["method"] not in ("GET", "HEAD", "OPTIONS") and (
                headers.get("origin") != self.settings.public_url
            ):
                rejection, status = deny("ORIGIN_REJECTED"), 403
        elif path.startswith(("/api/", "/mcp")):
            context, rejection, status = bearer(
                self.service.engine, headers.get("authorization"), self.service.now(),
                self.limits, meta, self.settings.bootstrap_token.get_secret_value(),
            )
        if rejection:
            audit = True
            if status == 401 and not path.startswith("/admin/"):
                audit, summary = self.limits.failure(meta["client_ip"], self.service.now())
                if not audit:
                    rejection, status = deny("RATE_LIMITED"), 429
                    if summary:
                        self.service.record(context, rejection, "auth.rate_limit_summary")
            if audit:
                self.service.record(context, rejection, "auth.authenticate")
            response_headers = {}
            if path == "/mcp" and status == 401:
                response_headers["WWW-Authenticate"] = (
                    'Bearer resource_metadata="' + self.settings.public_url
                    + '/.well-known/oauth-protected-resource"'
                )
            if status == 429:
                response_headers["Retry-After"] = "60"
            body = {"code": rejection["code"]} if path == "/mcp" else rejection
            return await JSONResponse(body, status_code=status, headers=response_headers)(
                scope, receive, send,
            )
        if path.startswith("/mcp"):
            host = headers.get("host", "").split(":")[0]
            permitted = {urlsplit(self.settings.public_url).hostname, "localhost", "127.0.0.1"}
            permitted.update(filter(None, self.settings.allowed_hosts.split(",")))
            if host not in permitted:
                self.service.record(context, deny("HOST_REJECTED"), "mcp.transport")
                return await JSONResponse({"code": "HOST_REJECTED"}, status_code=421)(
                    scope, receive, send,
                )
            self.service.protocol(context)
        elif path == "/health":
            self.service.protocol(context, "health.alias")
        token = current_context.set(context)
        service_token = current_service.set(self.service)
        try:
            await self.app(scope, receive, send)
        finally:
            current_context.reset(token)
            current_service.reset(service_token)
