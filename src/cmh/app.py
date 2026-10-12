"""Single ASGI service. No Flask imports and no separate MCP port."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from starlette.routing import Route

from cmh.api.health import health_router
from cmh.api.identity import identity_router
from cmh.auth.limits import RateLimits
from cmh.auth.middleware import IdentityMiddleware
from cmh.config import load_settings
from cmh.db.engine import build_engine, build_session_factory
from cmh.db.roles import guard_runtime_role
from cmh.logging import RequestIDMiddleware, configure_logging
from cmh.mcp.server import build_mcp
from cmh.services.core import IdentityService


def create_app() -> FastAPI:
    settings = load_settings()
    database_url = settings.database_url.get_secret_value()
    token = settings.bootstrap_token.get_secret_value()
    configure_logging((database_url, token))
    engine = build_engine(database_url)
    guard_runtime_role(engine, settings.env)
    server = build_mcp(settings)
    mcp_app = server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with server.session_manager.run():
                yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="CMH", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.mcp = server
    app.state.clock = lambda: datetime.now(UTC)
    app.state.limits = RateLimits()
    service = IdentityService(engine, lambda: app.state.clock())
    app.state.identity_service = service
    app.include_router(health_router(engine, settings.env))
    app.include_router(identity_router(settings))
    # ASGI Route mounts the MCP sub-app at the exact path without Mount's
    # automatic slash redirect or duplicated /mcp prefix. Its internal route
    # is also /mcp; the original scope path is deliberately preserved.
    app.router.routes.append(Route("/mcp", endpoint=mcp_app, methods=["GET", "POST", "DELETE"]))
    app.add_middleware(IdentityMiddleware, service=service, settings=settings,
                       limits=app.state.limits)
    app.add_middleware(RequestIDMiddleware)
    return app
