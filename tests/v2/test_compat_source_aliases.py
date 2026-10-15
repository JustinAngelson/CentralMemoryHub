"""Explicit v1 source aliases share inline-tag normalization on compatibility paths."""
import json
from decimal import Decimal

import pytest
from test_phase2_kernel import context, rows

from cmh.services.provenance import REF_REQUIRED, SOURCE_TYPES, provenance

ALIASES = [
    ("direct", "conversation"),
    ("reported", "human_input"),
    ("consolidated", "agent_inference"),
    ("memory-maintenance", "agent_inference"),
    ("reconstructed", "agent_inference"),
    ("inferred", "agent_inference"),
]


def provenance_fields(case, source):
    return {"source_type": source, "confidence": 0.42,
            "occurred_at": case.clock().isoformat()}


def last_source(case):
    return rows(case, """
        SELECT source_type,confidence FROM entities
        WHERE namespace_id=(SELECT id FROM namespaces WHERE path=CAST(:path AS ltree))
        ORDER BY created_at DESC,id DESC LIMIT 1
    """, path=case.namespace)[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("alias,canonical", ALIASES)
@pytest.mark.parametrize("surface", ["mcp-memory", "mcp-decision", "legacy-rest"])
async def test_explicit_source_aliases_on_compatibility_surfaces(identity, alias, canonical, surface):
    fields = provenance_fields(identity, alias) | {"namespace": identity.namespace}
    if surface == "legacy-rest":
        response = identity.bearer(identity.owner_token, "POST", "/memory/unstructured",
                                   json=fields | {"content": "Fictional alias write"})
        assert response.status_code == 201
    else:
        tool = "cmh_store_memory" if surface == "mcp-memory" else "cmh_log_decision"
        payload = {"content": "Fictional alias write", "title": "Fictional title"} if (
            surface == "mcp-memory"
        ) else {
            "context": "Fictional alias decision", "decision_text": "Use shared normalization",
            "made_by_agent": identity.owner["slug"],
        }
        async with identity.mcp(identity.owner_token) as session:
            result = await session.call_tool(tool, {"params": fields | payload})
        assert not result.isError
    stored = last_source(identity)
    assert stored["source_type"] == canonical
    assert stored["confidence"] == Decimal("0.42")  # Preserve explicit confidence exactly.
    tagged, _, error = provenance(context(identity, identity.owner_token), {
        "content": f"[source: {alias}] Fictional inline equivalent",
    }, identity.clock(), compatibility=True)
    assert error is None and tagged["source_type"] == stored["source_type"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["cmh_store_memory", "cmh_log_decision"])
async def test_unknown_explicit_source_still_denied_on_compatibility_tools(identity, tool):
    payload = {"content": "[source: direct] Fictional unknown source"} if tool.endswith("memory") else {
        "context": "Fictional unknown source", "decision_text": "Must reject",
        "made_by_agent": identity.owner["slug"],
    }
    async with identity.mcp(identity.owner_token) as session:
        result = await session.call_tool(tool, {"params": payload | {
            "namespace": identity.namespace, "source_type": "unrecognized-source",
        }})
    assert result.isError
    denied = json.loads(result.content[0].text)
    assert denied["code"] == "VALIDATION_FAILED" and denied["outcome"] == "DENY"
    assert result.structuredContent == denied
    assert last_source_or_none(identity) is None


def last_source_or_none(case):
    records = rows(case, """
        SELECT id FROM entities WHERE namespace_id=
          (SELECT id FROM namespaces WHERE path=CAST(:path AS ltree))
    """, path=case.namespace)
    return records[0] if records else None


def test_unknown_explicit_source_still_rejected_by_legacy_rest(identity):
    response = identity.bearer(identity.owner_token, "POST", "/memory/unstructured", json={
        "content": "Fictional unknown source", "namespace": identity.namespace,
        "source_type": "unrecognized-source",
    })
    assert response.status_code == 400
    assert last_source_or_none(identity) is None


@pytest.mark.parametrize("alias,_canonical", ALIASES)
def test_native_memory_endpoint_keeps_canonical_only_validation(identity, alias, _canonical):
    response = identity.bearer(identity.owner_token, "POST", "/api/memory", json={
        "content": "Fictional native source", "namespace": identity.namespace,
        **provenance_fields(identity, alias),
    })
    assert response.status_code == 403
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert last_source_or_none(identity) is None


@pytest.mark.parametrize("canonical", sorted(SOURCE_TYPES))
def test_canonical_sources_unchanged_on_compatibility_path(identity, canonical):
    payload = {"content": "Fictional canonical source", "namespace": identity.namespace,
               **provenance_fields(identity, canonical)}
    if canonical in REF_REQUIRED:
        payload["source_ref"] = "fictional-reference"
    made = identity.app.state.memory_service.store(
        context(identity, identity.owner_token), payload, compatibility=True,
    )
    assert "id" in made
    assert last_source(identity)["source_type"] == canonical


def test_explicit_alias_takes_precedence_over_inline_tag_without_changing_confidence(identity):
    made = identity.app.state.memory_service.store(context(identity, identity.owner_token), {
        "content": "[source: reported] Fictional conflicting source",
        "namespace": identity.namespace, **provenance_fields(identity, "direct"),
    }, compatibility=True)
    assert "id" in made
    assert last_source(identity) == {"source_type": "conversation", "confidence": Decimal("0.42")}
