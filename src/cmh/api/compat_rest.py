"""Two literal v1 REST contracts, backed exclusively by the v2 permission kernel."""
import json
from urllib.parse import parse_qs

from fastapi import APIRouter, Request

from cmh.api.identity import response
from cmh.auth.context import current_context
from cmh.policy.evaluator import deny


async def payload_from(request):
    """v1 accepts JSON, URL-encoded forms and raw JSON irrespective of MIME type."""
    try:
        raw = (await request.body()).decode("utf-8")
        if request.headers.get("content-type", "").split(";")[0] == "application/x-www-form-urlencoded":
            return {key: values[0] for key, values in parse_qs(raw, keep_blank_values=True).items()}
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, UnicodeError):
        return {}


def compatibility_router(memory):
    router = APIRouter()

    def failure(body, field):
        if body.get("code") in {"VALIDATION_FAILED", "PROVENANCE_INCOMPLETE"}:
            return response({"error": "Validation error", "message": "Invalid " + field,
                             "field": field}, 400)
        return response(body)

    @router.post("/memory/unstructured")
    async def store(request: Request):
        payload = await payload_from(request)
        body = memory.store(current_context.get(), payload, compatibility=True)
        if "id" not in body:
            return failure(body, "content")
        return response({"id": body["id"], "pinecone_id": str(body["id"]),
                         "message": "Unstructured memory added successfully"}, 201)

    @router.post("/search")
    async def search(request: Request):
        payload = await payload_from(request)
        try:
            limit = payload.get("top_k", 10)
            if isinstance(limit, str) and limit.isdigit():
                limit = int(limit)
            body = memory.search(current_context.get(), {
                **payload, "limit": limit, "kinds": ["memory"],
            })
        except Exception as error:  # noqa: BLE001 — literal v1 error boundary, never raw DB text
            # Preserve the legacy error envelope, not DB exception text/parameters.
            memory.identity.record(current_context.get(), deny("SEARCH_FAILED"), "memory.read")
            return response({
                "error": "Search operation failed", "message": "Search operation failed",
                "query": payload.get("query", "Unknown"),
                "debug_info": {"exception_type": type(error).__name__,
                               "pinecone_status": {"backend": "pgvector", "status": "unavailable"}},
            }, 500)
        if "results" not in body:
            return failure(body, "query")
        return response({"query": payload["query"], "results": [{
            "id": row.get("legacy_meta", {}).get("v1_id", str(row["id"])),
            "content": row["content"],
            "pinecone_id": row.get("legacy_meta", {}).get("pinecone_id") or str(row["id"]),
            "similarity_score": row["similarity_score"],
        } for row in body["results"]]})

    return router
