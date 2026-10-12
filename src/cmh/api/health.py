"""Unauthenticated readiness, with strictly sanitized failure output."""

import logging

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from cmh import __version__
from cmh.db.roles import guard_runtime_role


def health_router(engine, environment: str) -> APIRouter:
    router = APIRouter()

    @router.get("/health", include_in_schema=False)
    @router.get("/healthz")
    def health():
        extensions = {"vector": False, "ltree": False, "pgcrypto": False}
        body = {"version": __version__, "env": environment, "extensions": extensions,
                "db_role": "ok"}
        try:
            try:
                body["db_role"] = guard_runtime_role(engine, environment)
            except RuntimeError as condition:
                body["db_role"] = str(condition)
            with engine.connect() as connection:
                installed = set(connection.execute(text(
                    "SELECT extname FROM pg_extension "
                    "WHERE extname IN ('vector', 'ltree', 'pgcrypto')"
                )).scalars())
            for name in extensions:
                extensions[name] = name in installed
            ready = all(extensions.values()) and body["db_role"] == "ok"
            return JSONResponse(
                {**body, "status": "ok" if ready else "degraded", "database": "ok"},
                status_code=200 if ready else 503,
            )
        except SQLAlchemyError:
            logging.getLogger("cmh").warning("database_unreachable")
            return JSONResponse(
                {**body, "db_role": "unknown", "status": "unavailable",
                 "database": "unreachable"}, status_code=503
            )

    return router
