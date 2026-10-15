"""Three Phase 2A memory tools: required v1 params envelope and exact success text."""

import json
from datetime import datetime
from typing import Any

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, Field

from cmh.auth.context import current_context


class StoreMemoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", hide_input_in_errors=True)
    content: str = Field(min_length=1, max_length=10000)
    title: str | None = None
    namespace: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    confidence: Any = None
    occurred_at: Any = None
    author: Any = None
    author_id: Any = None
    author_principal_id: Any = None
    principal_id: Any = None
    agent_slug: Any = None
    gpt_role: Any = None
    actor: Any = None


class GetMemoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", hide_input_in_errors=True)
    id: str = Field(min_length=1)
    as_of: datetime | None = None


class SearchMemoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore", hide_input_in_errors=True)
    query: str = Field(min_length=1, max_length=1000)
    namespace: str | None = None
    kinds: list[str] | None = None
    anchor_entity_id: str | None = None
    depth: int = 3
    as_of: datetime | None = None
    limit: int = 10


def register_memory_tools(server, service):
    def result(body, success):
        if body.get("outcome") == "DENY":
            return CallToolResult(isError=True, content=[
                TextContent(type="text", text=json.dumps(body, default=str)),
            ], structuredContent=body)
        return CallToolResult(content=[TextContent(type="text", text=success(body))])

    @server.tool(name="cmh_store_memory")
    def store(params: StoreMemoryInput) -> CallToolResult:
        """Store memory. Legacy params are accepted; caller claims never set the author."""
        body = service.store(current_context.get(), params.model_dump(exclude_unset=True),
                             compatibility=True)
        return result(body, lambda value: (
            f"Memory stored successfully.\nID: {value['id']}\nPinecone ID: {value['pinecone_id']}"
        ))

    @server.tool(name="cmh_get_memory")
    def get(params: GetMemoryInput) -> CallToolResult:
        """Get a readable memory by v2 UUID or v1 identity."""
        body = service.get(current_context.get(), params.id, params.as_of)
        return result(body, lambda value: json.dumps({
            "id": str(value["id"]), "content": value["content"], "pinecone_id": value["pinecone_id"],
        }, indent=2))

    @server.tool(name="cmh_search_memory")
    def search(params: SearchMemoryInput) -> CallToolResult:
        """Search readable canonical entities with hybrid fusion and optional graph/as-of filters."""
        body = service.search(current_context.get(), params.model_dump(exclude_unset=True))
        if body.get("outcome") == "DENY":
            return result(body, None)
        rows = body["results"]
        formatted = "\n\n---\n\n".join(
            f'[{index}] (score: {row["similarity_score"]:.3f}) [id: {row["id"]}]\n{row["content"]}'
            for index, row in enumerate(rows, 1)
        )
        message = f'Found {len(rows)} result(s) for "{params.query}":\n\n{formatted}' if rows else (
            f'No memories found matching: "{params.query}"'
        )
        # Claude displays structuredContent instead of text when both are present.
        # Successful searches must preserve the v1 text-only response contract.
        if body["degraded"]:
            message += "\n(Note: semantic search unavailable; keyword results only.)"
        return CallToolResult(content=[TextContent(type="text", text=message)])
