"""Tests-first Phase 2A contract. No real embeddings, v1 connections or Pinecone."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from contract_helpers import denied
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

NATIVE = {
    "memory": ("memories", {"content": "kernel contract"}),
    "decision": ("decisions", {"decision_text": "kernel contract"}),
    "knowledge": ("knowledge", {"term": "kernel", "definition": "kernel contract"}),
    "org_state": ("org_states", {"state_key": "kernel", "state": {"status": "example"}}),
    "task": ("tasks", {"title": "kernel contract"}),
    "experiment": ("experiments", {"title": "kernel contract"}),
    "insight": ("insights", {"summary": "kernel contract"}),
    "shared_context": ("shared_contexts", {"context_tag": "kernel contract"}),
    "inbox_item": ("inbox_items", {"content": "kernel contract"}),
    "memory_link": ("memory_links", {"summary": "kernel contract"}),
}
MIRRORED = {
    "org": ("orgs", {"name": "Example Mechanical"}),
    "engagement": ("engagements", {"name": "example engagement"}),
    "project": ("projects", {"name": "example project"}),
    "note": ("notes", {"body": "kernel contract"}),
}


def store(case, content="kernel contract", credential=None, **extra):
    return case.bearer(credential or case.agent_a["credential"], "POST", "/api/memory", json={
        "content": content, "source_type": "agent_inference", "confidence": 0.7,
        "occurred_at": case.clock().isoformat(), **extra,
    })


def search(case, query="kernel", credential=None, **extra):
    return case.bearer(credential or case.owner_token, "POST", "/api/memory/search",
                       json={"query": query, **extra})


def rows(case, statement, **params):
    # Independent state inspection, not an application query missing its RLS setting.
    with case.admin.connect() as conn:
        return conn.execute(text(statement), params).mappings().all()


def context(case, credential=None):
    from cmh.auth.context import PrincipalContext

    credential = credential or case.agent_a["credential"]
    row = dict(case.sql("SELECT * FROM credentials WHERE id=:id", id=credential["id"])[0])
    subject = dict(case.sql("SELECT * FROM principals WHERE id=:id", id=row["principal_id"])[0])
    return PrincipalContext(subject, row, request_meta={"surface": "rest"})


def fixture_entity(case, kind, data, namespace="org", identity=None):
    """Approved administrative mirror fixtures; never an application write bypass."""
    entity_id = identity or uuid4()
    table = (NATIVE | MIRRORED)[kind][0]
    with case.admin.begin() as conn:
        ns = conn.execute(text("SELECT id FROM namespaces WHERE path=CAST(:p AS ltree)"),
                          {"p": namespace}).scalar_one()
        conn.execute(text("""
          INSERT INTO entities(id,kind,namespace_id,status,title,search_text,
            author_principal_id,actor,source_type,confidence,occurred_at)
          VALUES(:id,:kind,:ns,'canonical','kernel',:content,:author,
            'fixture','conversation',0.7,:now)
        """), {"id": entity_id, "kind": kind, "ns": ns, "content": " ".join(
            str(value) for value in data.values()
        ), "author": case.owner["id"], "now": case.clock()})
        values = {"id": entity_id, **data}
        expressions = [":" + key for key in values]
        if "state" in values:
            values["state"] = json.dumps(values["state"])
            expressions[list(values).index("state")] = "CAST(:state AS jsonb)"
        conn.execute(text(f"INSERT INTO {table} ({','.join(values)}) "
                          f"VALUES ({','.join(expressions)})"), values)
        if kind == "memory_link":
            target = conn.execute(text(
                "SELECT id FROM entities WHERE kind='memory' ORDER BY created_at DESC LIMIT 1"
            )).scalar_one()
            conn.execute(text("""
              INSERT INTO edges(src_entity_id,dst_entity_id,type,author_principal_id,actor,status)
              VALUES(:src,:dst,'about',:author,'fixture','active')
            """), {"src": entity_id, "dst": target, "author": case.owner["id"]})
        snapshot = dict(conn.execute(text("SELECT * FROM entities WHERE id=:id"),
                                     {"id": entity_id}).mappings().one())
        snapshot.pop("search_tsv")
        snapshot.update(data)
        conn.execute(text("""
          INSERT INTO entity_versions(entity_id,version,snapshot,status,change_kind,
            changed_by,actor,changed_at)
          VALUES(:id,1,CAST(:snapshot AS jsonb),'canonical','create',:author,'fixture',:now)
        """), {"id": entity_id, "snapshot": json.dumps(snapshot, default=str),
               "author": case.owner["id"], "now": case.clock()})
    return str(entity_id)


@pytest.mark.asyncio
async def test_T2A_1_v1_shape_defaults_author_actor_sponsor_and_exact_format(identity):
    async with identity.mcp(identity.agent_a["credential"]) as session:
        result = await session.call_tool("cmh_store_memory", {"params": {"content": "kernel default"}})
    assert not result.isError
    lines = result.content[0].text.splitlines()
    assert lines[0] == "Memory stored successfully."
    entity_id = lines[1].removeprefix("ID: ")
    assert lines[2] == "Pinecone ID: None"
    row = rows(identity, "SELECT * FROM entities WHERE id=:id", id=entity_id)[0]
    assert row["kind"] == "memory" and row["status"] == "canonical"
    assert str(row["author_principal_id"]) == identity.agent_a["principal"]["id"]
    assert row["actor"] == identity.agent_a["credential"]["name"]
    assert row["source_type"] == "agent_inference" and float(row["confidence"]) == 0.7
    assert row["occurred_at"] == identity.clock()
    assert row["legacy_meta"]["provenance_defaulted"] is True
    event = identity.audit()[-1]
    assert str(event["sponsor_id"]) == str(identity.partner_a["id"])


@pytest.mark.asyncio
async def test_T2A_2_leading_tags_never_set_author(identity):
    content = "[source: direct] [agent: agent_b1] [date: 2026-09-01] kernel tags"
    async with identity.mcp(identity.agent_a["credential"]) as session:
        result = await session.call_tool("cmh_store_memory", {"params": {"content": content}})
    assert not result.isError
    entity_id = result.content[0].text.splitlines()[1].removeprefix("ID: ")
    row = rows(identity, "SELECT * FROM entities WHERE id=:id", id=entity_id)[0]
    assert row["source_type"] == "conversation" and float(row["confidence"]) == 0.85
    assert row["occurred_at"] == datetime(2026, 9, 1, tzinfo=UTC)
    assert str(row["author_principal_id"]) == identity.agent_a["principal"]["id"]
    assert row["legacy_meta"]["claimed"]["agent"] == "agent_b1"
    assert row["legacy_meta"]["original_tags"] == content.split(" kernel")[0]


@pytest.mark.parametrize("extra,code", [
    ({"confidence": 1.3}, "VALIDATION_FAILED"),
    ({"confidence": -0.1}, "VALIDATION_FAILED"),
    ({"source_type": None}, "PROVENANCE_INCOMPLETE"),
    *[({"source_type": source, "source_ref": None}, "PROVENANCE_INCOMPLETE")
      for source in ("document", "tool_output", "meeting_intelligence", "source_sync")],
])
def test_3_provenance_strict_validation_and_durable_denial(identity, extra, code):
    content = "invalid-provenance-" + uuid4().hex
    denied(store(identity, content, **extra), code, step=7)
    assert not rows(identity, "SELECT id FROM memories WHERE content=:c", c=content)
    assert identity.audit()[-1]["outcome"] == "DENY"


def test_3_4_rest_ignores_spoofed_author_and_actor(identity):
    response = store(identity, "strict REST authorship", author_principal_id=identity.partner_b["id"],
                     actor="not-the-caller")
    assert response.status_code == 201
    row = rows(identity, "SELECT * FROM entities WHERE id=:id", id=response.json()["id"])[0]
    assert str(row["author_principal_id"]) == identity.agent_a["principal"]["id"]
    assert row["actor"] == identity.agent_a["credential"]["name"]
    assert row["legacy_meta"]["claimed"]["author_principal_id"] == identity.partner_b["id"]
    assert row["legacy_meta"]["claimed"]["actor"] == "not-the-caller"


@pytest.mark.asyncio
@pytest.mark.parametrize("extra,code", [
    ({"confidence": 1.3}, "VALIDATION_FAILED"),
    ({"source_type": "document"}, "PROVENANCE_INCOMPLETE"),
])
async def test_T2A_3_compat_provided_provenance_remains_strict(identity, extra, code):
    async with identity.mcp(identity.agent_a["credential"]) as session:
        result = await session.call_tool("cmh_store_memory",
                                         {"params": {"content": "compat invalid", **extra}})
    assert result.isError and json.loads(result.content[0].text)["code"] == code
    assert identity.audit()[-1]["outcome"] == "DENY"


@pytest.mark.parametrize("namespace", ["private", "org.finance"])
def test_T2A_4_agent_cannot_write_private_or_finance(identity, namespace):
    path = "people." + identity.partner_b["slug"] + ".private" if (
        namespace == "private"
    ) else namespace
    denied(store(identity, namespace=path), "NAMESPACE_FORBIDDEN", step=5)


def test_1_15_readonly_personal_real_write_scope_missing(identity):
    denied(store(identity, credential=identity.readonly_token), "SCOPE_MISSING", step=2)


@pytest.mark.asyncio
async def test_1_11_real_mcp_write_ignores_spoofed_identity(identity):
    async with identity.mcp(identity.agent_a["credential"]) as session:
        result = await session.call_tool("cmh_store_memory", {"params": {
            "content": "identity-spoof", "author_principal_id": identity.partner_b["id"],
            "actor": "partner_b", "principal_id": identity.partner_b["id"],
        }})
    assert not result.isError
    entity_id = result.content[0].text.splitlines()[1].removeprefix("ID: ")
    row = rows(identity, "SELECT author_principal_id,actor FROM entities WHERE id=:id",
               id=entity_id)[0]
    assert str(row["author_principal_id"]) == identity.agent_a["principal"]["id"]
    assert row["actor"] == identity.agent_a["credential"]["name"]


def test_2A_5_sponsor_revocation_blocks_real_write(identity):
    assert store(identity).status_code == 201
    identity.tamper("""
      DELETE FROM namespace_grants WHERE principal_id=:id AND namespace_id=
        (SELECT id FROM namespaces WHERE path='org')
    """, id=identity.partner_a["id"])
    denied(store(identity, "revoked sponsor"), "SPONSOR_CEILING", step=4)


def test_T2A_5_private_search_owner_exclusion_and_partner_access(identity):
    agent_private = "agents." + identity.agent_a["principal"]["slug"] + ".private"
    marker_a = "private_agent_" + uuid4().hex
    assert store(identity, marker_a, namespace=agent_private).status_code == 201
    assert all(row["content"] != marker_a for row in search(
        identity, marker_a, identity.agent_b["credential"],
    ).json()["results"])
    private = "people." + identity.partner_a["slug"] + ".private"
    personal = identity.credential(identity.client_a, identity.partner_a, "personal-ai-client")
    marker_b = "private_partner_" + uuid4().hex
    assert store(identity, marker_b, personal, namespace=private).status_code == 201
    assert all(row["content"] != marker_b for row in search(identity, marker_b).json()["results"])
    assert any(row["content"] == marker_b for row in search(
        identity, marker_b, personal,
    ).json()["results"])


def test_T2A_6_uuid_v1_and_indistinguishable_not_found(identity):
    created = store(identity).json()
    assert "id" in created
    identity.tamper("""
      UPDATE entities SET legacy_meta='{"v1_table":"unstructured_data","v1_id":"old-id",
        "pinecone_id":"archived-id"}' WHERE id=:id
    """, id=created["id"])
    for entity_id in (created["id"], "v1:unstructured_data:old-id"):
        result = identity.bearer(identity.owner_token, path="/api/memory/" + entity_id)
        assert result.status_code == 200 and result.json()["id"] == created["id"]
        assert result.json()["pinecone_id"] == "archived-id"
    private = "people." + identity.partner_a["slug"] + ".private"
    secret = fixture_entity(identity, "memory", {"content": "private unreadable"}, private)
    responses = [identity.bearer(identity.owner_token, path="/api/memory/" + value)
                 for value in (secret, str(uuid4()))]
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["code"] == "NOT_FOUND"


def test_5_3_keyword_semantic_fusion(identity):
    first = store(identity, "car safety", namespace=identity.namespace)
    second = store(identity, "automobile safety", namespace=identity.namespace)
    assert first.status_code == second.status_code == 201
    result = search(identity, "car", namespace=identity.namespace).json()["results"]
    assert [row["id"] for row in result][:2] == [first.json()["id"], second.json()["id"]]
    assert result[0]["similarity_score"] > result[1]["similarity_score"] > 0


def test_T2A_7_write_provider_failure_atomic_and_search_degraded(identity):
    assert store(identity, "outage keyword", namespace=identity.namespace).status_code == 201
    identity.app.state.embedding_provider.fail = True
    denied(store(identity, "must-not-commit"), "READ_ONLY_MODE")
    assert not rows(identity, "SELECT id FROM memories WHERE content='must-not-commit'")
    result = search(identity, "outage", namespace=identity.namespace)
    assert result.status_code == 200 and result.json()["degraded"] is True
    assert result.json()["results"][0]["content"] == "outage keyword"


def test_T2A_8_search_audit_filters_not_query_or_content(identity):
    marker = "audit_secret_" + uuid4().hex
    assert store(identity, marker, namespace=identity.namespace).status_code == 201
    result = search(identity, marker, namespace=identity.namespace, kinds=["memory"], limit=3)
    assert result.status_code == 200
    event = identity.audit()[-1]
    trace = event["decision_trace"]
    assert trace["filters"]["namespace"] == identity.namespace
    assert trace["filters"]["kinds"] == ["memory"]
    assert trace["result_count"] == len(result.json()["results"])
    assert marker not in json.dumps(event, default=str)


def test_T2A_9_fault_rolls_back_all_allow_state_but_denial_survives(identity):
    service = identity.app.state.entity_service
    before = identity.audit()[-1]["seq"]
    identities = []

    def fail(_connection, _identity):
        identities.append(_identity)
        raise RuntimeError("Injected after version")

    service.after_version = fail
    with pytest.raises(RuntimeError, match="Injected after version"):
        store(identity, "atomic-allow")
    service.after_version = None
    assert identity.audit()[-1]["seq"] == before
    assert not rows(identity, "SELECT id FROM entities WHERE search_text='atomic-allow'")
    assert not rows(identity, "SELECT id FROM memories WHERE content='atomic-allow'")
    for table in ("entity_versions", "embeddings"):
        assert not rows(identity, f"SELECT entity_id FROM {table} WHERE entity_id=:id",
                        id=identities[0])
    denied(store(identity, confidence=1.3), "VALIDATION_FAILED")
    assert identity.audit()[-1]["seq"] > before


def test_T2A_10_kind_scopes_drop_decision_without_error(identity):
    fixture_entity(identity, "decision", {"decision_text": "scope-limited"})
    identity.tamper("UPDATE credentials SET scopes=ARRAY['memory.read'] WHERE id=:id",
                    id=identity.owner_token["id"])
    result = search(identity, "scope-limited", kinds=["memory", "decision"])
    assert result.status_code == 200
    assert all(row["kind"] != "decision" for row in result.json()["results"])
    assert identity.audit()[-1]["decision_trace"]["filters"]["kinds"] == ["memory"]


@pytest.mark.parametrize("kind", list(NATIVE))
def test_5_1_typed_registry_bijection_and_memory_link_default_exclusion(identity, kind):
    assert store(identity).status_code == 201
    table, data = NATIVE[kind]
    entity_id = fixture_entity(identity, kind, data)
    assert rows(identity, f"SELECT id FROM {table} WHERE id=:id", id=entity_id)
    for other, (other_table, _) in NATIVE.items():
        if other != kind:
            assert not rows(identity, f"SELECT id FROM {other_table} WHERE id=:id", id=entity_id)
    if kind == "memory_link":
        assert all(row["kind"] != kind for row in search(identity).json()["results"])
    with pytest.raises(DBAPIError), identity.admin.begin() as conn:
        conn.execute(text("INSERT INTO memories(id,content) VALUES(:id,'wrong kind')"),
                     {"id": entity_id})


def test_5_2_version_update_and_point_in_time(identity):
    created = store(identity, "version before").json()
    assert "id" in created
    before = identity.clock()
    identity.clock.advance(seconds=2)
    updated = identity.app.state.entity_service.update(
        context(identity), created["id"], {"content": "version after"},
    )
    assert updated["current_version"] == 2
    old = identity.bearer(identity.owner_token, path="/api/memory/" + created["id"],
                          params={"as_of": before.isoformat()})
    assert old.json()["content"] == "version before"
    assert identity.bearer(identity.owner_token, path="/api/memory/" + created["id"]).json()[
        "content"
    ] == "version after"


@pytest.mark.parametrize("hidden_middle", [False, True])
def test_5_4_5_graph_walk_each_hop_readable_default_depth_three(identity, hidden_middle):
    assert store(identity).status_code == 201
    private = "people." + identity.partner_b["slug"] + ".private"
    org = fixture_entity(identity, "org", MIRRORED["org"][1])
    engagement = fixture_entity(identity, "engagement", MIRRORED["engagement"][1],
                                private if hidden_middle else "org")
    project = fixture_entity(identity, "project", MIRRORED["project"][1])
    note = fixture_entity(identity, "note", {"body": "graph reachable"})
    memory = store(identity, "graph reachable").json()["id"]
    unrelated = store(identity, "graph unreachable").json()["id"]
    for src, dst, edge_type in [
        (org, engagement, "has_engagement"), (engagement, project, "delivered_by"),
        (note, engagement, "note_on"), (memory, project, "about"),
    ]:
        identity.tamper("""
          INSERT INTO edges(src_entity_id,dst_entity_id,type,author_principal_id,actor,status,
            valid_from)
          VALUES(:src,:dst,:type,:author,'fixture','active',:now)
        """, src=src, dst=dst, type=edge_type, author=identity.owner["id"], now=identity.clock())
    result = search(identity, "graph", anchor_entity_id=org, kinds=["memory", "note"]).json()
    ids = {row["id"] for row in result["results"]}
    assert unrelated not in ids
    assert (note in ids and memory in ids) is not hidden_middle
    assert not ids if hidden_middle else len(ids) == 2


def test_5_8_rls_backstop_without_explicit_filter_and_missing_setting(identity):
    readable = store(identity).json()["id"]
    private = "people." + identity.partner_b["slug"] + ".private"
    hidden = fixture_entity(identity, "memory", {"content": "rls hidden"}, private)
    with identity.engine.begin() as conn:
        assert not conn.execute(text("SELECT id FROM entities")).all()
        ns = conn.execute(text("SELECT id FROM namespaces WHERE path='org'")).scalar_one()
        conn.execute(text("SELECT set_config('cmh.readable_namespaces',:ns,true)"), {"ns": str(ns)})
        ids = {str(value) for value in conn.execute(text("SELECT id FROM entities")).scalars()}
        assert readable in ids and hidden not in ids
        for table in ("memories", "entity_versions", "embeddings"):
            column = "id" if table == "memories" else "entity_id"
            assert not conn.execute(text(f"SELECT 1 FROM {table} WHERE {column}=:id"),
                                    {"id": hidden}).all()
        assert conn.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname='cmh_app'")).scalar(
        ) is False
        assert conn.execute(text(
            "SELECT tableowner FROM pg_tables WHERE schemaname='public' AND tablename='entities'"
        )).scalar_one() != "cmh_app"


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_4_4b_versions_are_append_only(identity, operation):
    assert store(identity).status_code == 201
    with pytest.raises(DBAPIError, match="permission denied"), identity.engine.begin() as conn:
        conn.execute(text({
            "UPDATE": "UPDATE entity_versions SET actor='mutated'",
            "DELETE": "DELETE FROM entity_versions",
            "TRUNCATE": "TRUNCATE entity_versions",
        }[operation]))


@pytest.mark.no_app_operation(reason="Kernel migration round trip and role grant inspection.")
def test_T2A_11_kernel_migration_round_trip(test_database, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from conftest import ROOT
    from sqlalchemy import create_engine

    from cmh.db.engine import normalize_database_url

    config = Config(str(ROOT / "v2/alembic.ini"))
    monkeypatch.setenv("CMH_MIGRATE_DATABASE_URL", test_database)
    command.downgrade(config, "0002_identity")
    command.upgrade(config, "head")
    with create_engine(normalize_database_url(test_database), hide_parameters=True).connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0003_memory_kernel"
        )
        for permission in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not conn.execute(text(
                "SELECT has_table_privilege('cmh_app','entity_versions',:p)"
            ), {"p": permission}).scalar_one()


@pytest.fixture
def mismatched_dimension_boot(configured_env, role_login_engine, monkeypatch):
    import cmh.app
    from cmh.services.embedding import FakeEmbeddingProvider

    monkeypatch.setenv("CMH_ENV", "dev")
    monkeypatch.setattr(cmh.app, "build_engine", lambda _: role_login_engine._engine)
    monkeypatch.setattr(cmh.app, "build_embedding_provider",
                        lambda _: FakeEmbeddingProvider(dimensions=1024))
    with pytest.raises(RuntimeError) as error:
        cmh.app.create_app()
    return str(error.value)


@pytest.mark.no_app_operation(reason="Embedding dimension startup configuration guard.")
def test_5_6_dimension_mismatch_refuses_start(mismatched_dimension_boot):
    assert "dimension" in mismatched_dimension_boot.lower()


@pytest.fixture
def unavailable_embedding_boot(identity, monkeypatch):
    import cmh.app
    from cmh.services.embedding import FakeEmbeddingProvider

    provider = FakeEmbeddingProvider()
    provider.fail = True
    monkeypatch.setattr(cmh.app, "build_embedding_provider", lambda _: provider)
    return cmh.app.create_app()


def test_5_7_provider_down_at_boot_degraded_health_and_readonly(
    identity, unavailable_embedding_boot,
):
    from fastapi.testclient import TestClient

    with TestClient(unavailable_embedding_boot) as client:
        result = client.get("/healthz")
        assert result.status_code == 503
        assert result.json()["status"] == "degraded"
        assert result.json()["embeddings"] == "unavailable"
        body = unavailable_embedding_boot.state.memory_service.store(context(identity), {
            "content": "boot outage write", "source_type": "agent_inference", "confidence": 0.7,
            "occurred_at": identity.clock().isoformat(),
        })
        assert body["code"] == "READ_ONLY_MODE" and body["outcome"] == "DENY"


@pytest.fixture
def unsafe_version_privilege_boot(configured_env, role_login_engine, audit_admin, monkeypatch):
    import cmh.app

    monkeypatch.setenv("CMH_ENV", "dev")
    monkeypatch.setattr(cmh.app, "build_engine", lambda _: role_login_engine._engine)
    healthy = cmh.app.create_app()
    with audit_admin.begin() as conn:
        conn.execute(text("GRANT UPDATE ON entity_versions TO cmh_app"))
    try:
        with pytest.raises(RuntimeError) as error:
            cmh.app.create_app()
        yield healthy, str(error.value)
    finally:
        with audit_admin.begin() as conn:
            conn.execute(text("REVOKE UPDATE ON entity_versions FROM cmh_app"))


@pytest.mark.no_app_operation(reason="Only GET /healthz: append-only version role startup guard.")
def test_T2A_12_startup_and_health_reject_mutable_versions(unsafe_version_privilege_boot):
    from fastapi.testclient import TestClient

    app, error = unsafe_version_privilege_boot
    assert "entity_versions" in error
    with TestClient(app) as client:
        response = client.get("/healthz")
        assert response.status_code == 503
        assert "entity_versions" in response.json()["db_role"]


@pytest.mark.no_app_operation(reason="Migration schema validation: Phase 4A tables stay absent.")
def test_P5_skills_resources_and_assignments_are_deferred(audit_admin):
    with audit_admin.connect() as conn:
        for name in ("skills", "resources", "skill_files", "principal_skill_assignments"):
            assert conn.execute(text("SELECT to_regclass(:name)"), {"name": name}).scalar() is None


@pytest.mark.asyncio
async def test_P8_memory_get_exact_json_labels_and_search_text(identity):
    created = store(identity, "format contract", namespace=identity.namespace)
    assert created.status_code == 201
    entity_id = created.json()["id"]
    async with identity.mcp(identity.owner_token) as session:
        got = await session.call_tool("cmh_get_memory", {"params": {"id": entity_id}})
        assert got.content[0].text == json.dumps({
            "id": entity_id, "content": "format contract", "pinecone_id": None,
        }, indent=2)
        found = await session.call_tool("cmh_search_memory", {
            "params": {"query": "format", "namespace": identity.namespace},
        })
    assert not found.isError
    assert found.content[0].text.startswith('Found 1 result(s) for "format":\n\n[1] (score: ')
    assert found.content[0].text.endswith(f") [id: {entity_id}]\nformat contract")


def test_private_descendants_inherit_owner_exclusion_and_partner_access(identity):
    path = "people." + identity.partner_a["slug"] + ".private.child"
    created = identity.request(identity.owner_client, "POST", "/admin/api/namespaces",
                               json={"path": path})
    assert created.status_code == 201
    denied(identity.check(identity.owner_token, "memory.read", path), "NAMESPACE_FORBIDDEN", step=5)
    personal = identity.credential(identity.client_a, identity.partner_a, "personal-ai-client")
    assert identity.check(personal, "memory.read", path).json()["outcome"] == "ALLOW"
