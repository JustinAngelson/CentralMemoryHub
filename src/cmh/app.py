"""Single ASGI service. No Flask imports and no separate MCP port."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.routing import Route

from cmh.api.health import health_router
from cmh.api.identity import identity_router
from cmh.api.memory import memory_router
from cmh.auth.limits import RateLimits
from cmh.auth.middleware import IdentityMiddleware
from cmh.config import load_settings
from cmh.db.engine import build_engine, build_session_factory
from cmh.db.roles import guard_runtime_role
from cmh.logging import RequestIDMiddleware, configure_logging
from cmh.mcp.server import build_mcp
from cmh.services.core import IdentityService
from cmh.services.embedding import EmbeddingUnavailable, build_embedding_provider
from cmh.services.entities import EntityService
from cmh.services.memory import MemoryService


def create_app(clock=None) -> FastAPI:
    # The boot probe and the request-time recovery must use the same clock.
    initial_clock = clock or (lambda: datetime.now(UTC))
    settings = load_settings()
    database_url = settings.database_url.get_secret_value()
    token = settings.bootstrap_token.get_secret_value()
    configure_logging((database_url, token))
    engine = build_engine(database_url)
    guard_runtime_role(engine, settings.env)
    service = IdentityService(engine, lambda: app.state.clock())
    provider = build_embedding_provider(settings)
    entities = EntityService(service, provider, settings.embedding_retry_seconds)
    try:
        with engine.connect() as connection:
            dimensions = connection.execute(text("""
              SELECT atttypmod FROM pg_attribute
              WHERE attrelid=to_regclass('public.embeddings') AND attname='embedding'
            """)).scalar()
        if dimensions is not None and dimensions != provider.dimensions:
            raise RuntimeError("Embedding provider/column dimension mismatch")
        provider.embed("cmh embedding readiness")
    except (EmbeddingUnavailable, SQLAlchemyError):
        entities.embedding_failed(initial_clock())
    memory = MemoryService(entities)
    server = build_mcp(settings, memory)
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
    app.state.clock = initial_clock
    app.state.limits = RateLimits()
    app.state.identity_service = service
    app.state.entity_service = entities
    app.state.memory_service = memory
    app.state.embedding_provider = provider
    app.state.entities = entities
    from pathlib import Path

    from starlette.staticfiles import StaticFiles

    from cmh.api.compat_rest import compatibility_router
    from cmh.api.public import PublicSecurityHeaders, public_router

    app.servers = [{"url": settings.public_url}]
    app.include_router(public_router(service, settings))
    app.include_router(compatibility_router(memory))
    app.mount("/public", StaticFiles(directory=Path(__file__).parent / "public"), name="public")
    app.include_router(health_router(engine, settings.env, entities))
    app.include_router(identity_router(settings))
    app.include_router(memory_router(memory))
    # ASGI Route mounts the MCP sub-app at the exact path without Mount's
    # automatic slash redirect or duplicated /mcp prefix. Its internal route
    # is also /mcp; the original scope path is deliberately preserved.
    app.router.routes.append(Route("/mcp", endpoint=mcp_app, methods=["GET", "POST", "DELETE"]))
    app.add_middleware(IdentityMiddleware, service=service, settings=settings,
                       limits=app.state.limits)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(PublicSecurityHeaders)
    return app
