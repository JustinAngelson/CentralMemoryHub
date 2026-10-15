"""Real MCP transport regression: Claude must receive the legacy search text."""

import json
import re

import pytest
from test_phase2_kernel import store


@pytest.mark.asyncio
@pytest.mark.parametrize("degraded", [False, True])
@pytest.mark.parametrize("empty", [False, True])
async def test_search_success_is_text_only_with_legacy_format(identity, degraded, empty):
    content = "structured search compatibility contract"
    created = store(identity, content, namespace=identity.namespace)
    assert created.status_code == 201
    entity_id = created.json()["id"]
    # The SDK harness creates a separate application; fail its provider, not
    # the REST fixture's provider, so the fault reaches the actual MCP request.
    identity.start_mcp()
    identity.server.config.app.state.embedding_provider.fail = degraded
    query = "structured"
    params = {"query": query, "namespace": identity.namespace,
              "kinds": ["decision"] if empty else ["memory"]}
    async with identity.mcp(identity.owner_token) as session:
        result = await session.call_tool("cmh_search_memory", {"params": params})

    assert not result.isError
    assert result.structuredContent is None
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    message = result.content[0].text
    note = "\n(Note: semantic search unavailable; keyword results only.)" if degraded else ""
    if empty:
        assert message == f'No memories found matching: "{query}"' + note
    else:
        score = r"0\.000" if degraded else r"\d\.\d{3}"
        expected = (
            re.escape(f'Found 1 result(s) for "{query}":\n\n[1] (score: ')
            + score
            + re.escape(f") [id: {entity_id}]\n{content}" + note)
        )
        assert re.fullmatch(expected, message)


@pytest.mark.asyncio
async def test_search_denial_keeps_structured_error_envelope(identity):
    async with identity.mcp(identity.owner_token) as session:
        result = await session.call_tool("cmh_search_memory", {"params": {
            "query": "structured", "namespace": "invalid/namespace",
        }})
    assert result.isError
    body = json.loads(result.content[0].text)
    assert body["outcome"] == "DENY"
    assert body["code"] == "NAMESPACE_FORBIDDEN"
    assert result.structuredContent == body
