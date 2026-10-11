"""TEMPORARY Phase 0 bearer gate, isolated for replacement in Phase 1."""

import hmac
from contextvars import ContextVar

from starlette.responses import JSONResponse

principal: ContextVar[str | None] = ContextVar("cmh_principal", default=None)


class BootstrapAuthMiddleware:
    def __init__(self, app, token: str):
        self.app = app
        self.token = token.encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/mcp":
            return await self.app(scope, receive, send)
        values = [
            value for key, value in scope.get("headers", [])
            if key.lower() == b"authorization"
        ]
        code = "AUTH_MISSING" if not values else "AUTH_INVALID"
        authenticated = False
        if len(values) == 1:
            pieces = values[0].split(b" ")
            if len(pieces) == 2 and pieces[0].lower() == b"bearer" and pieces[1]:
                authenticated = hmac.compare_digest(pieces[1], self.token)
        if not authenticated:
            response = JSONResponse(
                {"code": code}, status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="cmh"'},
            )
            return await response(scope, receive, send)
        context = principal.set("bootstrap")
        try:
            await self.app(scope, receive, send)
        finally:
            principal.reset(context)
