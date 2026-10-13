"""The two active v1 REST contracts, backed exclusively by the v2 permission kernel."""
from fastapi import APIRouter, Request

from cmh.api.identity import response
from cmh.auth.context import current_context


def compatibility_router(memory):
    router = APIRouter()

    @router.post("/memory/unstructured")
    async def store(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise TypeError()
        except (ValueError, TypeError):
            payload = {}
        body = memory.store(current_context.get(), payload, compatibility=True)
        if "id" not in body:
            return response(body)
        return response({"id": body["id"], "pinecone_id": str(body["id"]),
                         "message": "Unstructured memory added successfully"}, 201)

    @router.post("/search")
    async def search(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise TypeError()
        except (ValueError, TypeError):
            payload = {}
        body = memory.search(current_context.get(), {**payload, "limit": payload.get("top_k", 5),
                                                    "kinds": ["memory"]})
        if "results" in body:
            for result in body["results"]:
                result["similarity_score"] = result["similarity_score"]
                result["pinecone_id"] = result.get("legacy_meta", {}).get("pinecone_id") or result["id"]
            body["query"] = payload.get("query")
        return response(body)

    return router
