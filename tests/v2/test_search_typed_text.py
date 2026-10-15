"""Typed display and historical keyword regressions, through real MCP transport."""

import json
import re
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_phase2_kernel import context, rows, store

from cmh.kernel import DEFAULT_KINDS, MIRRORED, TYPED
from cmh.services.entities import encode


def typed_record(case, kind):
    marker = "needle" + kind.replace("_", "")
    data = {}
    for field, datatype in TYPED[kind][1].items():
        if datatype == "text":
            data[field] = "Typed heading" if field == "title" else f"{marker} {field}"
        elif datatype == "text[]":
            data[field] = [f"{marker} {field} first", f"{marker} {field} second"]
        elif datatype == "jsonb":
            data[field] = {"hidden": "jsonmustnotbedisplayed"}
    provenance = {"source_type": "agent_inference", "confidence": 0.7,
                  "occurred_at": case.clock()}
    service = case.app.state.entity_service
    owner = context(case, case.owner_token)
    if kind not in MIRRORED | {"inbox_item"}:
        created = service.create(owner, kind, data, provenance, path=case.namespace,
                                 title="Typed heading")
        assert "id" in created
        entity_id = str(created["id"])
    else:
        # Mirrors are not native writes; inbox submission is External-only.
        # Build these fixtures using the real version writer, without storing
        # derived search_text or relaxing application permissions.
        entity_id = str(uuid4())
        with case.admin.begin() as conn:
            namespace = conn.execute(text(
                "SELECT id FROM namespaces WHERE path=CAST(:path AS ltree)"
            ), {"path": case.namespace}).scalar_one()
            row = dict(conn.execute(text("""
                INSERT INTO entities(id,kind,namespace_id,title,search_text,
                  author_principal_id,actor,source_type,confidence,occurred_at)
                VALUES(:id,:kind,:namespace,'Typed heading',:search_text,
                  :author,'fixture','agent_inference',0.7,:at) RETURNING *
            """), {"id": entity_id, "kind": kind, "namespace": namespace,
                   "search_text": " ".join(str(value) for value in data.values()),
                   "author": case.owner["id"], "at": case.clock()}).mappings().one())
            table, columns = TYPED[kind]
            fields = ["id", *data]
            values = {"id": entity_id, **data}
            expressions = []
            for field in fields:
                if columns.get(field) == "jsonb":
                    values[field] = encode(values[field])
                    expressions.append(f"CAST(:{field} AS jsonb)")
                else:
                    expressions.append(":" + field)
            conn.execute(text(f"INSERT INTO {table} ({','.join(fields)}) "
                              f"VALUES ({','.join(expressions)})"), values)
            typed = conn.execute(text(f"SELECT * FROM {table} WHERE id=:id"),
                                 {"id": entity_id}).mappings().one()
            service.version(conn, owner, {**row, **typed}, "create",
                            service.provider.embed(marker))
    if kind in {"memory", "note"}:
        expected = data["content" if kind == "memory" else "body"]
    else:
        parts = ["Typed heading"]
        for field, datatype in TYPED[kind][1].items():
            if field == "title":
                continue
            if datatype == "text":
                parts.append(data[field])
            elif datatype == "text[]":
                parts.extend(data[field])
        expected = "\n".join(parts)
    return entity_id, marker, data, expected


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", DEFAULT_KINDS)
async def test_default_kind_search_displays_typed_fields_mcp_and_json(identity, kind):
    entity_id, marker, _, expected = typed_record(identity, kind)
    versions_before = rows(identity, "SELECT snapshot FROM entity_versions WHERE entity_id=:id",
                           id=entity_id)
    assert all("search_text" not in row["snapshot"] for row in versions_before)
    async with identity.mcp(identity.owner_token) as session:
        result = await session.call_tool("cmh_search_memory", {"params": {
            "query": marker, "namespace": identity.namespace,
        }})
    assert not result.isError and result.structuredContent is None
    output = result.content[0].text
    assert marker in output
    assert output.endswith("\n" + expected)
    assert "jsonmustnotbedisplayed" not in output
    assert re.fullmatch(
        re.escape(f'Found 1 result(s) for "{marker}":\n\n[1] (score: ')
        + r"\d\.\d{3}" + re.escape(f") [id: {entity_id}]\n{expected}"), output,
    )
    native = identity.bearer(identity.owner_token, "POST", "/api/memory/search", json={
        "query": marker, "namespace": identity.namespace,
    })
    assert native.status_code == 200
    assert native.json()["results"][0]["content"] == expected
    assert rows(identity, "SELECT snapshot FROM entity_versions WHERE entity_id=:id",
                id=entity_id) == versions_before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,field", [
    ("decision", "rationale"), ("knowledge", "synonyms"), ("memory", "content"),
])
async def test_as_of_keyword_search_matches_past_non_title_field(identity, kind, field):
    entity_id, _, _, _ = typed_record(identity, kind)
    old_word = "archiveduniqueword"
    new_word = "replacementuniqueword"
    value = [old_word, "otherword"] if TYPED[kind][1][field] == "text[]" else old_word
    service = identity.app.state.entity_service
    owner = context(identity, identity.owner_token)
    identity.clock.advance(seconds=1)
    assert service.update(owner, entity_id, {field: value})["current_version"] == 2
    at = identity.clock()
    identity.clock.advance(seconds=1)
    replacement = [new_word] if isinstance(value, list) else new_word
    assert service.update(owner, entity_id, {field: replacement})["current_version"] == 3
    before = rows(identity, "SELECT snapshot FROM entity_versions WHERE entity_id=:id "
                  "ORDER BY version", id=entity_id)
    assert all("search_text" not in row["snapshot"] for row in before)
    # Disable semantic retrieval in the actual transport app: only historical
    # keyword matching can find this result, not a vector or the current index.
    identity.start_mcp()
    identity.server.config.app.state.embedding_provider.fail = True
    async with identity.mcp(identity.owner_token) as session:
        past = await session.call_tool("cmh_search_memory", {"params": {
            "query": old_word, "namespace": identity.namespace, "as_of": at.isoformat(),
        }})
        current = await session.call_tool("cmh_search_memory", {"params": {
            "query": old_word, "namespace": identity.namespace,
        }})
        future = await session.call_tool("cmh_search_memory", {"params": {
            "query": new_word, "namespace": identity.namespace, "as_of": at.isoformat(),
        }})
    assert not past.isError and past.structuredContent is None
    assert f"[id: {entity_id}]" in past.content[0].text
    assert old_word in past.content[0].text and new_word not in past.content[0].text
    assert current.content[0].text.startswith("No memories found")
    assert future.content[0].text.startswith("No memories found")
    assert rows(identity, "SELECT snapshot FROM entity_versions WHERE entity_id=:id "
                "ORDER BY version", id=entity_id) == before


@pytest.mark.asyncio
async def test_memory_mcp_bytes_and_legacy_rest_content_unchanged(identity):
    content = "bytecontract\nSecond line: [source: raw]\n\nLast line."
    created = store(identity, content, namespace=identity.namespace)
    assert created.status_code == 201
    entity_id = created.json()["id"]
    async with identity.mcp(identity.owner_token) as session:
        result = await session.call_tool("cmh_search_memory", {"params": {
            "query": "bytecontract", "namespace": identity.namespace,
        }})
    assert not result.isError and result.structuredContent is None
    expected = re.escape('Found 1 result(s) for "bytecontract":\n\n[1] (score: ')
    assert re.fullmatch(expected + r"\d\.\d{3}" + re.escape(
        f") [id: {entity_id}]\n{content}"), result.content[0].text)
    rest = identity.bearer(identity.owner_token, "POST", "/search", json={
        "query": "bytecontract", "namespace": identity.namespace,
    })
    assert rest.status_code == 200
    assert rest.json()["results"][0]["content"] == content


@pytest.mark.asyncio
async def test_typed_search_deny_envelope_unchanged(identity):
    async with identity.mcp(identity.owner_token) as session:
        denied = await session.call_tool("cmh_search_memory", {"params": {
            "query": "needle", "namespace": "invalid/path",
        }})
    assert denied.isError
    body = json.loads(denied.content[0].text)
    assert body["outcome"] == "DENY" and body["code"] == "NAMESPACE_FORBIDDEN"
    assert denied.structuredContent == body
