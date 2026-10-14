"""Thin strict memory REST adapter; never derives identity from request fields."""

from fastapi import APIRouter, Request

from cmh.api.identity import response
from cmh.auth.context import current_context


def memory_router(service):
    router = APIRouter()

    async def payload(request):
        try:
            value = await request.json()
            return value if isinstance(value, dict) else {}
        except (ValueError, TypeError):
            # Empty inputs still go through permission checks, then the shared
            # validator records VALIDATION_FAILED. Never trust a client sentinel.
            return {}

    @router.post("/api/memory")
    async def store(request: Request):
        body = service.store(current_context.get(), await payload(request))
        return response(body, 201)

    @router.get("/api/memory/{identity}")
    def get(identity: str, as_of: str | None = None):
        return response(service.get(current_context.get(), identity, as_of))

    @router.post("/api/memory/search")
    async def search(request: Request):
        body = service.search(current_context.get(), await payload(request))
        return response(body)

    return router
