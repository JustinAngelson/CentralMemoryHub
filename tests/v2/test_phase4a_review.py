"""R11–R16: real schema columns, narrow legacy transport and bounded public ingress."""
import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import SensitiveTestValue
from sqlalchemy import text
from test_phase4a_apply import context, native_roster

from cmh.importing.shapes import KINDS, shape

WHEN = datetime(2024, 2, 3, 4, 5, tzinfo=UTC)
LATER = WHEN + timedelta(days=1)
SCHEMA = Path(__file__).parent / "fixtures" / "v1_schema.sql"


def real_columns(table):
    block = re.search(r"CREATE TABLE public\." + table + r" \((.*?)\n\);",
                      SCHEMA.read_text(), re.DOTALL)[1]
    return dict(re.findall(r'^\s+"?(\w+)"?\s+([^,\n]+)', block, re.MULTILINE))


def real_row(table):
    row = {}
    for key, definition in real_columns(table).items():
        row[key] = (WHEN if definition.startswith("timestamp") else
                    1 if definition.startswith("integer") else
                    True if definition.startswith("boolean") else
                    [] if definition.startswith("json") else
                    str(uuid4()) if key.endswith("_id") or key == "id" else
                    "Fictional " + key)
    if "updated_at" in row:
        row["updated_at"] = LATER
    return row


def assert_real_columns(table):
    row = real_row(table)
    assert set(row) == set(real_columns(table)) and all(value is not None for value in row.values())
    item = shape(table, row, "fixture", {}, {}, LATER + timedelta(days=10))
    fields = item["legacy_meta"].get("v1_fields", {})
    assert not {key for key, definition in real_columns(table).items()
                if definition.startswith("timestamp")} & fields.keys()
    date_field = {"decision_log": "timestamp", "project_decisions": "timestamp",
                  "shared_contexts": "timestamp", "user_insights": "timestamp",
                  "memory_links": "timestamp_added", "skill_files": "uploaded_at",
                  "org_profile": "updated_at"}.get(table, "created_at")
    if date_field in row:
        assert item["created_at"] == row[date_field]
        assert item["provenance"]["occurred_at"] == row[date_field]
    if table == "unstructured_data":
        assert item["legacy_meta"]["occurred_at_unknown"]
    if table == "agent_tasks":
        assert item["data"]["due_at"] == WHEN
    if table == "memory_links":
        assert item["data"]["linked_event_ref"] == row["linked_agent_event"]


def test_R11_real_schema_roundtrip_values_references_and_projection(identity, tmp_path):
    from cmh.importing.plan import write_csv
    from cmh.importing.runner import ImportRunner
    from cmh.importing.source import INVENTORY
    from cmh.services.compat import CompatService

    case = identity
    runner = ImportRunner(case.app.state.entities, context(case))
    for table in sorted(KINDS):
        assert_real_columns(table)
    rows = {table: real_row(table) for table in (*KINDS, "agent_sessions", "gpt_messages")}
    actor = case.agent_a["principal"]["slug"]
    for row in rows.values():
        for field in ("gpt_role", "made_by_agent", "created_by_agent", "owner_agent",
                      "last_updated_by", "sender", "sender_agent", "receiver_agent",
                      "assigned_to_agent", "executing_agent", "agent_id", "user_id"):
            if field in row:
                row[field] = actor
    rows["shared_contexts"].update(recipients=[actor, "unresolved-fixture"],
        memory_refs=[rows["unstructured_data"]["id"], "unresolved-memory"])
    rows["kb_index"]["used_by_agents"] = [actor, "unresolved-fixture"]
    rows["memory_links"]["pinecone_vector_id"] = rows["unstructured_data"]["pinecone_id"]
    rows["gpt_messages"]["session_id"] = rows["agent_sessions"]["session_id"]
    rows["skill_files"]["skill_id"] = rows["skills"]["id"]
    tables = {name: [rows[name]] if name in rows else [] for name in INVENTORY}
    keys = {table: [next(key for key in real_columns(table)
                        if key == "id" or key.endswith("_id"))] for table in rows}
    source = {"tables": tables, "counts": {t: len(r) for t, r in tables.items()},
              "primary_keys": keys}
    roster = native_roster(case)
    attribution = [{"value": actor, "count": "1", "proposed_principal": actor}]
    mappings = [{"v1_table": t, "v1_id": str(r[keys[t][0]]),
                 "proposed_namespace": case.namespace, "matched_aliases": "", "reason": "fixture"}
                for t, r in rows.items()]
    for name, values in (("roster", roster), ("attribution", attribution), ("namespace_mapping", mappings)):
        filename = name + "_review.csv" if name != "namespace_mapping" else name + ".csv"
        write_csv(tmp_path / filename, values, list(values[0]))
    report = runner.apply(source, tmp_path)
    assert report["complete"] and report["imported"] == len(rows)
    compat = CompatService(case.app.state.memory_service)
    for table, tool, value_key, source_key, time_key in (
        ("decision_log", "cmh_list_decisions", "decision_text", "decision_text", "timestamp"),
        ("user_insights", "cmh_list_user_insights", "summary", "summary", "timestamp"),
        ("shared_contexts", "cmh_list_contexts", "context_tag", "context_tag", "timestamp"),
        ("agent_tasks", "cmh_list_tasks", "title", "title", "due_date"),
        ("memory_links", "cmh_list_memory_links", "linked_agent_event", "linked_agent_event", "timestamp_added"),
        ("gpt_messages", "cmh_list_messages", "content", "content", "timestamp"),
    ):
        from cmh.mcp.compat_formats import format_success
        listed = compat.call(context(case), tool, {"namespace": case.namespace})
        projected = json.loads(format_success(tool, listed))[0]
        assert projected[value_key] == rows[table][source_key]
        assert datetime.fromisoformat(projected[time_key]) == WHEN
    state = compat.call(context(case), "cmh_list_org_states", {"namespace": case.namespace})
    state = next(row for row in state if row["legacy_meta"]["v1_table"] == "org_state")
    assert state["state_key"] == rows["org_state"]["entity"]
    assert state["state"]["owner_agent"] == actor
    with case.admin.connect() as conn:
        entity = conn.execute(text("""SELECT * FROM entities
          WHERE namespace_id=(SELECT id FROM namespaces WHERE path=CAST(:path AS ltree))
          AND legacy_meta->>'v1_table'='shared_contexts'"""), {"path": case.namespace}).mappings().one()
        assert str(entity["author_principal_id"]) == str(case.agent_a["principal"]["id"])
        typed = conn.execute(text("SELECT * FROM shared_contexts WHERE id=:id"),
                             {"id": entity["id"]}).mappings().one()
        assert len(typed["recipient_principal_ids"]) == len(typed["memory_ref_entity_ids"]) == 1
        assert entity["legacy_meta"]["unresolved"]["memory_refs"] == ["unresolved-memory"]
        assert entity["legacy_meta"]["unresolved"]["recipients"] == ["unresolved-fixture"]
        assert conn.execute(text("""SELECT cardinality(used_by_principal_ids) FROM knowledge
          WHERE id=(SELECT id FROM entities WHERE legacy_meta->>'v1_id'=:id)"""),
          {"id": rows["kb_index"]["index_id"]}).scalar_one() == 1


@pytest.fixture
def legacy_rest(identity):
    case = identity
    found = case.sql("SELECT * FROM principals WHERE slug='legacy-rest'")
    if found:
        subject = found[0]
    else:
        result = case.request(case.owner_client, "POST", "/admin/api/principals", json={
            "kind": "service", "slug": "legacy-rest", "display_name": "Legacy REST",
            "sponsor_id": str(case.owner["id"]), "template": "service-integration",
            "scopes": ["memory.read", "memory.write"],
        }).json()
        if result.get("outcome") == "QUEUE":
            result = case.request(case.owner_client, "POST",
                                  "/admin/api/approvals/" + result["approval_id"] + "/approve").json()
        subject = result["principal"]
    grant = case.request(case.owner_client, "POST", "/admin/api/grants", json={
        "principal_id": str(subject["id"]), "namespace": "org", "permission": "write",
    })
    assert grant.status_code in (200, 201)
    key = SensitiveTestValue(secrets.token_urlsafe(32))
    registered = case.request(case.owner_client, "POST", "/admin/api/credentials/import", json={
        "principal_id": str(subject["id"]), "token": key, "name": "legacy-rest",
    })
    assert registered.status_code == 201
    for index in range(10):
        stored = case.app.state.memory_service.store(context(case), {
            "content": "Fictional search fixture " + str(index),
        }, compatibility=True)
        assert "id" in stored
    return key


@pytest.mark.parametrize("encoding", ["json", "form", "raw"])
def test_R12_R13_R16_legacy_key_exact_shapes_default_ten_and_body_formats(identity, legacy_rest, encoding):
    case = identity
    payload = {"content": "Fictional legacy REST marker " + case.namespace}
    def send(path, data, **headers):
        headers = {"x-aPi-kEy": legacy_rest, **headers}
        options = ({"json": data} if encoding == "json" else {"data": data}
                   if encoding == "form" else {"content": json.dumps(data),
                                                "headers": {"content-type": "text/plain"}})
        headers.update(options.pop("headers", {}))
        return case.owner_client.post(path, headers=headers, **options)
    stored = send("/memory/unstructured", payload)
    assert stored.status_code == 201
    assert set(stored.json()) == {"id", "pinecone_id", "message"}
    legacy_id = "source-" + case.namespace
    case.tamper("UPDATE entities SET legacy_meta=jsonb_build_object('v1_id',CAST(:old AS text)) WHERE id=:id",
                old=legacy_id, id=stored.json()["id"])
    case.tamper("""UPDATE entity_versions SET snapshot=jsonb_set(
        snapshot,'{legacy_meta}',jsonb_build_object('v1_id',CAST(:old AS text)))
        WHERE entity_id=:id""", old=legacy_id, id=stored.json()["id"])
    found = send("/search", {"query": payload["content"]})
    assert found.status_code == 200 and set(found.json()) == {"query", "results"}
    assert len(found.json()["results"]) == 10
    for row in found.json()["results"]:
        assert set(row) == {"id", "content", "pinecone_id", "similarity_score"}
    assert found.json()["results"][0]["id"] == legacy_id
    assert send("/search", {"query": "fictional"}, Authorization="").status_code == 401
    assert send("/memory/unstructured", {"content": "x" * 10001}).status_code == 400


def test_R12_key_ignored_elsewhere_wrong_key_limited_and_namespace_scoped(identity, legacy_rest):
    client = identity.owner_client
    for path in ("/mcp", "/api/memory/search"):
        assert client.post(path, headers={"X-API-KEY": legacy_rest}, json={}).status_code == 401
    client._transport.client = ("198.51.100.25", 50000)
    for index in range(30):
        header = {"Authorization": "Bearer wrong"} if index < 15 else {"X-API-KEY": "wrong"}
        assert client.post("/search", headers=header, json={"query": "x"}).status_code == 401
    assert client.post("/search", headers={"X-API-KEY": "wrong"}, json={"query": "x"}).status_code == 429
    assert client.post("/memory/unstructured", headers={"X-API-KEY": legacy_rest},
                       json={"content": "fixture", "namespace": "org.finance"}).status_code == 403


def test_R13_search_failure_uses_v1_error_envelope(identity, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic search failure")
    monkeypatch.setattr(identity.app.state.memory_service, "search", fail)
    response = identity.bearer(identity.owner_token, "POST", "/search", json={"query": "fixture"})
    assert response.status_code == 500
    assert set(response.json()) == {"error", "message", "query", "debug_info"}
    assert response.json()["error"] == "Search operation failed"
    assert set(response.json()["debug_info"]) == {"exception_type", "pinecone_status"}


def test_R14_public_noise_adds_no_audit_and_attempts_are_bounded(identity):
    import hashlib
    import hmac

    case = identity
    client = case.owner_client
    client._transport.client = ("198.51.100.24", 50000)
    ip_hash = hmac.new(case.bootstrap.encode(), b"198.51.100.24", hashlib.sha256).hexdigest()
    with case.admin.connect() as conn:
        before = conn.execute(text("SELECT max(seq) FROM audit_events")).scalar_one()
    for _ in range(50):
        assert client.get("/").status_code == 200
        assert client.post("/api/waitlist", json={"email": "bad"}).status_code in (400, 429)
    with case.admin.connect() as conn:
        assert conn.execute(text("SELECT max(seq) FROM audit_events")).scalar_one() == before
        assert conn.execute(text("SELECT count(*) FROM waitlist_attempts WHERE ip_hash=:ip"),
                            {"ip": ip_hash}).scalar_one() == 5
    case.clock.advance(hours=2)
    accepted = client.post("/api/waitlist", json={
        "first_name": "Example", "email": case.namespace + "@example.invalid",
    })
    assert accepted.status_code == 200
    with case.admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM waitlist_attempts")).scalar_one() == 1
        assert conn.execute(text("SELECT count(*) FROM audit_events WHERE seq>:seq"),
                            {"seq": before}).scalar_one() == 1
    client.post("/api/waitlist", json={"first_name": "Example", "email": case.namespace + "@example.invalid"})
    with case.admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit_events WHERE seq>:seq"),
                            {"seq": before}).scalar_one() == 1


@pytest.mark.asyncio
async def test_R15_R16_real_external_and_agent_denied_owner_partner_allowed(identity):
    case = identity
    external = case.request(case.owner_client, "POST", "/admin/api/principals", json={
        "kind": "agent", "slug": "external-" + uuid4().hex, "display_name": "External Test",
        "role": "external", "tier": 1,
        "sponsor_id": str(case.owner["id"]), "template": "external-readonly",
        "namespace_grants": [{"path": case.namespace, "access": "read"}],
    }).json()
    external = case.request(case.owner_client, "POST",
        "/admin/api/approvals/" + external["approval_id"] + "/approve").json()
    partner_token = case.credential(case.client_a, case.partner_a, "personal-ai-client")
    for credential, allowed in ((case.owner_token, True), (partner_token, True),
                                (external["credential"], False), (case.agent_a["credential"], False)):
        async with case.mcp(credential) as session:
            called = await session.call_tool("cmh_verify_audit_chain", {})
            assert called.isError is not allowed
            value = json.loads(called.content[0].text)
            assert value.get("valid") is True if allowed else value["outcome"] == "DENY"
    for path, allowed in ((case.namespace, True), ("org.finance", False)):
        checked = case.check(external["credential"], "memory.read", path)
        assert (checked.status_code == 200) is allowed
    ids = {}
    for path in (case.namespace, "org.finance"):
        stored = case.app.state.memory_service.store(context(case), {
            "content": "Fictional External visibility " + case.namespace, "namespace": path,
        }, compatibility=True)
        assert "id" in stored
        ids[path] = str(stored["id"])
    found = case.bearer(external["credential"], "POST", "/search", json={
        "query": "Fictional External visibility " + case.namespace,
    })
    assert found.status_code == 200
    assert {row["id"] for row in found.json()["results"]} == {ids[case.namespace]}
    assert case.bearer(external["credential"], "POST", "/memory/unstructured", json={
        "content": "External cannot write", "namespace": case.namespace,
    }).status_code == 403
