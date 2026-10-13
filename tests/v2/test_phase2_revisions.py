"""Accepted 2A review fixes, committed failing before implementation."""

import json
from uuid import uuid4

import pytest
from contract_helpers import denied
from test_phase2_kernel import context, rows, search, store


@pytest.mark.parametrize("failure", ["write", "search", "boot"])
def test_R1_cooldown_and_recovery(identity, monkeypatch, failure):
    from fastapi.testclient import TestClient

    import cmh.app
    from cmh.services.embedding import FakeEmbeddingProvider

    app = identity.app
    if failure == "boot":
        provider = FakeEmbeddingProvider()
        provider.fail = True
        monkeypatch.setattr(cmh.app, "build_embedding_provider", lambda _: provider)
        app = cmh.app.create_app()
        app.state.clock = identity.clock
    provider = app.state.embedding_provider
    service = app.state.memory_service
    payload = {"content": "recovery contract", "source_type": "agent_inference",
               "confidence": 0.7, "occurred_at": identity.clock().isoformat()}
    if failure != "boot":
        provider.fail = True
        if failure == "write":
            denied(service.store(context(identity), payload), "READ_ONLY_MODE")
        else:
            assert service.search(context(identity), {"query": "recovery"})["degraded"] is True
    denied(service.store(context(identity), payload), "READ_ONLY_MODE")
    provider.fail = False
    denied(service.store(context(identity), payload), "READ_ONLY_MODE")
    identity.clock.advance(seconds=61)
    result = service.store(context(identity), payload)
    assert "id" in result and result.get("outcome") != "DENY"
    with TestClient(app) as client:
        health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["read_only"] is False and health.json()["status"] == "ok"


def test_R1_search_reprobes_only_after_cooldown(identity, monkeypatch):
    provider = identity.app.state.embedding_provider
    provider.fail = True
    assert search(identity).json()["degraded"] is True
    provider.fail = False
    original = provider.embed
    calls = []

    def embed(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(provider, "embed", embed)
    assert search(identity).json()["degraded"] is True
    assert calls == []
    identity.clock.advance(seconds=61)
    assert search(identity).json()["degraded"] is False
    assert calls
    assert identity.app.state.entity_service.read_only is False


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", ["[date: yesterday]", "[date: Oct 11 2026]",
                                 "[source: unknown-source]"])
async def test_R2_unparseable_inline_tag_is_archived_not_rejected(identity, tag):
    async with identity.mcp(identity.agent_a["credential"]) as session:
        result = await session.call_tool("cmh_store_memory", {"params": {
            "content": tag + " compatibility tag contract",
        }})
    assert not result.isError
    identity_id = result.content[0].text.splitlines()[1].removeprefix("ID: ")
    row = rows(identity, "SELECT * FROM entities WHERE id=:id", id=identity_id)[0]
    assert row["occurred_at"] == identity.clock()
    assert row["legacy_meta"]["provenance_defaulted"] is True
    assert tag in row["legacy_meta"]["unparsed_tags"]
    assert row["source_type"] == "agent_inference"


@pytest.mark.asyncio
async def test_R2_tool_argument_date_stays_strict(identity):
    async with identity.mcp(identity.agent_a["credential"]) as session:
        result = await session.call_tool("cmh_store_memory", {"params": {
            "content": "[date: yesterday] strict explicit date",
            "occurred_at": "yesterday",
        }})
    assert result.isError
    assert json.loads(result.content[0].text)["code"] == "VALIDATION_FAILED"


def private_search_namespace(case):
    path = "org.clients.test_" + uuid4().hex
    response = case.request(case.owner_client, "POST", "/admin/api/namespaces",
                            json={"path": path})
    assert response.status_code == 201
    return path


def test_R3_identical_score_and_keyword_only_score(identity, monkeypatch):
    path = private_search_namespace(identity)
    content = "identical cosine contract"
    assert store(identity, content, namespace=path).status_code == 201
    result = search(identity, content, namespace=path).json()["results"][0]
    assert result["similarity_score"] >= 0.99
    monkeypatch.setattr(identity.app.state.memory_service.vector_store, "top", lambda *args: [])
    keyword = search(identity, content, namespace=path).json()["results"][0]
    assert keyword["similarity_score"] >= 0.99


def test_R3_order_is_fusion_not_reported_cosine(identity):
    path = private_search_namespace(identity)
    exact = store(identity, "automobile", namespace=path).json()["id"]
    keyword = store(identity, "car road repairs", namespace=path).json()["id"]
    results = search(identity, "car", namespace=path).json()["results"]
    assert [row["id"] for row in results] == [keyword, exact]
    assert results[1]["similarity_score"] >= 0.99
    assert results[0]["similarity_score"] < results[1]["similarity_score"]
    identity.app.state.embedding_provider.fail = True
    degraded = search(identity, "car", namespace=path).json()
    assert degraded["degraded"] is True
    assert all(row["similarity_score"] == 0 for row in degraded["results"])
