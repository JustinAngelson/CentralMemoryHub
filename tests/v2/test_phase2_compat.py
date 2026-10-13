"""Phase 2B gate: inventory-driven payloads, identity, visibility and audit."""

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from test_phase2_kernel import context, rows

INVENTORY = json.loads((Path(__file__).parent / "fixtures/v1_tool_inventory.json").read_text())
TOOLS = {tool["name"]: tool for tool in INVENTORY["tools"]}
WRITES = [name for name in TOOLS if any(word in name for word in (
    "_store_", "_create_", "_update_", "_log_", "_send_", "_share_", "_end_",
))] + ["cmh_register_agent"]


def body(result):
    return result.content[0].text


def denial(result, code):
    assert result.isError
    value = json.loads(body(result))
    assert value["code"] == code and value["outcome"] == "DENY"
    return value


def sample(case, tool, ids):
    values = {}
    for field in TOOLS[tool]["fields"]:
        if not field["required"]:
            continue
        kind, name = field["type"], field["name"]
        values[name] = (["example"] if kind == "List[str]" else [0.1, 0.2]
                        if kind == "List[float]" else "example contract")
    values.update({key: case.agent_a["principal"]["slug"] for key in values if key in {
        "gpt_role", "made_by_agent", "created_by_agent", "sender_agent", "sender",
        "last_updated_by", "agent_id", "assigned_to_agent", "executing_agent", "owner_agent",
    }})
    replacements = {"pinecone_vector_id": ids["memory"], "session_id": ids["session"],
                    "task_id": ids["task"], "entity_id": ids["org_state"],
                    "user_id": case.partner_a["slug"], "status": "open", "type": "project",
                    "role": "automation", "message_type": "note"}
    values.update({key: value for key, value in replacements.items() if key in values})
    if tool == "cmh_get_memory":
        values["id"] = ids["memory"]
    if tool == "cmh_get_structured":
        values["id"] = ids["structured"]
    if tool == "cmh_search_memory":
        values["query"] = "compatibility"
    return {"params": values} if TOOLS[tool]["arguments"] else {}


@pytest.fixture
def compat_case(identity):
    case = identity
    display = "partner_agent_" + uuid4().hex
    case.tamper("UPDATE principals SET display_name=:name WHERE id=:id",
                name=display, id=case.agent_b["principal"]["id"])
    case.agent_b["principal"]["display_name"] = display
    legacy_ids = {kind: str(uuid4().int % (2**60))
                  for kind in ("structured", "task", "org_state", "session")}
    service = case.app.state.entity_service
    provenance = {"source_type": "agent_inference", "confidence": 0.7,
                  "occurred_at": case.clock()}
    definitions = {
        "memory": ("memory", {"content": "compatibility memory"}, {}),
        "structured": ("memory", {"content": "compatibility structured"}, {
            "original_table": "project_decisions", "v1_table": "project_decisions",
            "v1_id": legacy_ids["structured"],
            "v1_fields": {"context_embedding": [0.1, 0.2], "related_documents": ["example.md"]},
        }),
        "task": ("task", {"title": "compatibility task", "task_status": "open"}, {
            "v1_table": "agent_tasks", "v1_id": legacy_ids["task"]}),
        "org_state": ("org_state", {"state_key": "compatibility", "state": {
            "entity": "Example Mechanical", "status": "open", "type": "project",
        }}, {"v1_table": "org_state", "v1_id": legacy_ids["org_state"]}),
        "decision": ("decision", {"context": "example", "decision_text": "compatibility",
                                  "reversal_possible": True}, {}),
        "knowledge": ("knowledge", {"term": "compatibility"}, {}),
        "experiment": ("experiment", {"title": "compatibility", "hypothesis": "example"}, {}),
        "insight": ("insight", {"summary": "compatibility"}, {}),
        "shared_context": ("shared_context", {"context_tag": "compatibility"}, {}),
    }
    ids = {}
    for name, (kind, data, meta) in definitions.items():
        value = service.create(context(case), kind, data, provenance, legacy_meta=meta)
        assert "id" in value
        ids[name] = str(value["id"])
    ids["session"] = str(uuid4())
    ids["alias"] = "test_directory_alias_" + uuid4().hex
    ids.update({"legacy_" + kind: value for kind, value in legacy_ids.items()})
    with case.admin.begin() as conn:
        if conn.execute(text("SELECT to_regclass('public.sessions')")).scalar():
            conn.execute(text("""
              INSERT INTO sessions(id,principal_id,namespace_id,started_at,legacy_meta)
              SELECT :id,:principal,id,:now,CAST(:meta AS jsonb)
              FROM namespaces WHERE path='org'
            """), {"id": ids["session"], "principal": case.agent_a["principal"]["id"],
                   "now": case.clock(), "meta": json.dumps({
                       "v1_table": "agent_sessions", "v1_id": legacy_ids["session"],
                   })})
            conn.execute(text("""
              UPDATE agent_directory SET aliases=ARRAY[:alias]
              WHERE principal_id=:id
            """), {"id": case.agent_b["principal"]["id"], "alias": ids["alias"]})
    return case, ids


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(TOOLS))
async def test_T2B_1_v1_payload_and_response_format(compat_case, name):
    case, ids = compat_case
    async with case.mcp(case.agent_a["credential"]) as session:
        result = await session.call_tool(name, sample(case, name, ids))
    if name == "cmh_register_agent":
        denial(result, "PRINCIPAL_CREATION_FORBIDDEN")
        return
    assert not result.isError, body(result)
    response = TOOLS[name]["response"]
    text_value = body(result)
    if response["format"] == "json_object":
        assert set(response["top_level_fields"]) <= json.loads(text_value).keys()
    elif response["format"] == "json_array":
        if text_value.startswith("["):
            for row in json.loads(text_value):
                assert set(response["item_fields"]) <= row.keys()
        else:
            assert text_value.startswith("No ")
    elif response["format"] == "text":
        for label in response.get("text_labels", []):
            if not label.startswith(("Error", "No ", "Session not", "Session already",
                                     "Task not", "Org state not")):
                assert label + ":" in text_value
    if name == "cmh_health_check":
        assert json.loads(text_value)["pinecone"] == "not_used"


SELF_FIELDS = [
    ("cmh_store_structured", "gpt_role", "entities", "author_principal_id"),
    ("cmh_log_decision", "made_by_agent", "entities", "author_principal_id"),
    ("cmh_create_task", "created_by_agent", "entities", "author_principal_id"),
    ("cmh_send_message", "sender_agent", "messages", "sender_principal_id"),
    ("cmh_share_context", "sender", "entities", "author_principal_id"),
    ("cmh_create_org_state", "last_updated_by", "entities", "author_principal_id"),
    ("cmh_create_session", "agent_id", "sessions", "principal_id"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,field,table,column", SELF_FIELDS)
async def test_T2B_2_self_claims_never_set_author_and_trace_mismatch(
    compat_case, name, field, table, column,
):
    case, ids = compat_case
    payload = sample(case, name, ids)
    payload["params"][field] = case.agent_b["principal"]["slug"]
    async with case.mcp(case.agent_a["credential"]) as session:
        before = rows(case, "SELECT coalesce(max(seq),0) AS seq FROM audit_events")[0]["seq"]
        result = await session.call_tool(name, payload)
        events = rows(case, "SELECT * FROM audit_events WHERE seq>:seq "
                      "AND operation!='mcp.transport'", seq=before)
    assert not result.isError
    assert len(events) == 1
    assert events[0]["decision_trace"]["claimed_identity_mismatch"] is True
    row = rows(case, f"SELECT * FROM {table} WHERE id=:id",
               id=events[0]["resource_id"])[0]
    assert str(row[column]) == case.agent_a["principal"]["id"]
    assert row["legacy_meta"]["claimed"][field] == case.agent_b["principal"]["slug"]


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["slug", "display_name", "alias", "unknown"])
async def test_T2B_3_target_resolution_and_unknown_text(compat_case, target):
    case, ids = compat_case
    name = {"slug": case.agent_b["principal"]["slug"].upper(),
            "display_name": case.agent_b["principal"]["display_name"],
            "alias": ids["alias"].upper(), "unknown": "unknown target"}[target]
    payload = sample(case, "cmh_create_task", ids)
    payload["params"]["assigned_to_agent"] = name
    async with case.mcp(case.agent_a["credential"]) as session:
        response = await session.call_tool("cmh_create_task", payload)
    assert not response.isError
    identity_id = body(response).splitlines()[1].removeprefix("Task ID: ")
    row = rows(case, "SELECT e.legacy_meta,t.assignee_principal_id FROM tasks t "
               "JOIN entities e ON e.id=t.id WHERE t.id=:id", id=identity_id)[0]
    if target == "unknown":
        assert row["assignee_principal_id"] is None
        assert row["legacy_meta"]["unresolved"]["assigned_to_agent"] == name
    else:
        assert str(row["assignee_principal_id"]) == case.agent_b["principal"]["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,old_id", [("task", "42"), ("org_state", "43")])
@pytest.mark.parametrize("legacy", [True, False])
async def test_T2B_4_updates_version_and_historical_snapshot(compat_case, kind, old_id, legacy):
    case, ids = compat_case
    before = case.clock()
    case.clock.advance(seconds=2)
    name = "cmh_update_" + kind
    payload = sample(case, name, ids)
    field = "task_id" if kind == "task" else "entity_id"
    payload["params"][field] = ids["legacy_" + kind] if legacy else ids[kind]
    payload["params"]["status"] = "complete"
    async with case.mcp(case.agent_a["credential"]) as session:
        result = await session.call_tool(name, payload)
    assert not result.isError
    versions = rows(case, "SELECT * FROM entity_versions WHERE entity_id=:id ORDER BY version",
                    id=ids[kind])
    assert len(versions) == 2 and versions[0]["version"] == 1 and versions[1]["version"] == 2
    field = "task_status" if kind == "task" else "state"
    assert versions[0]["snapshot"][field] == (
        "open" if kind == "task" else {
            "entity": "Example Mechanical", "status": "open", "type": "project",
        }
    )
    service = case.app.state.entity_service
    with service.engine.begin() as conn:
        readable = service.scope(conn, context(case))
        row = service.find(conn, readable, ids[kind])
        assert service.snapshot(conn, row, readable, before)[field] == versions[0]["snapshot"][field]


@pytest.mark.asyncio
async def test_T2B_5_receiver_still_requires_namespace_and_rls(compat_case):
    case, ids = compat_case
    private = "agents." + case.agent_a["principal"]["slug"] + ".private"
    async with case.mcp(case.agent_a["credential"]) as session:
        for namespace in ("org", private):
            payload = sample(case, "cmh_send_message", ids)
            payload["params"].update(namespace=namespace,
                                     receiver_agent=case.agent_b["principal"]["slug"],
                                     content=namespace + " receiver visibility")
            assert not (await session.call_tool("cmh_send_message", payload)).isError
    async with case.mcp(case.agent_b["credential"]) as session:
        result = await session.call_tool("cmh_list_messages", {"params": {}})
    messages = json.loads(body(result))
    assert any(row["content"] == "org receiver visibility" for row in messages)
    assert not any(row["content"] == private + " receiver visibility" for row in messages)
    with case.app.state.engine.begin() as conn:
        conn.execute(text("SELECT set_config('cmh.readable_namespaces','',true)"))
        assert conn.execute(text("SELECT count(*) FROM messages")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM sessions")).scalar() == 0


@pytest.mark.asyncio
async def test_T2B_6_session_owned_by_caller_ended_and_filtered(compat_case):
    case, ids = compat_case
    payload = sample(case, "cmh_create_session", ids)
    payload["params"].update(agent_id=case.agent_b["principal"]["slug"],
                             namespace="agents." + case.agent_a["principal"]["slug"] + ".private")
    async with case.mcp(case.agent_a["credential"]) as session:
        result = await session.call_tool("cmh_create_session", payload)
        session_id = body(result).splitlines()[1].removeprefix("Session ID: ")
        assert not (await session.call_tool(
            "cmh_end_session", {"params": {"session_id": session_id}},
        )).isError
        visible = await session.call_tool("cmh_list_sessions", {"params": {}})
    assert any(row["session_id"] == session_id and row["ended_at"]
               for row in json.loads(body(visible)))
    row = rows(case, "SELECT * FROM sessions WHERE id=:id", id=session_id)[0]
    assert str(row["principal_id"]) == case.agent_a["principal"]["id"]
    async with case.mcp(case.agent_b["credential"]) as session:
        hidden = await session.call_tool("cmh_list_sessions", {"params": {}})
    assert not any(row["session_id"] == session_id for row in json.loads(body(hidden)))


@pytest.mark.asyncio
async def test_T2B_7_links_archive_id_and_indistinguishable_target(compat_case):
    case, ids = compat_case
    case.tamper("UPDATE entities SET legacy_meta=legacy_meta||"
                "'{\"pinecone_id\":\"archived-example-vector\"}' WHERE id=:id",
                id=ids["memory"])
    async with case.mcp(case.agent_a["credential"]) as session:
        for identity_id in (ids["memory"], "archived-example-vector"):
            result = await session.call_tool("cmh_create_memory_link", {"params": {
                "pinecone_vector_id": identity_id, "linked_agent_event": "opaque historical event",
            }})
            assert not result.isError
        missing = await session.call_tool("cmh_create_memory_link", {"params": {
            "pinecone_vector_id": str(uuid4()),
        }})
    denial(missing, "EDGE_ENDPOINT_FORBIDDEN")
    provenance = {"source_type": "agent_inference", "confidence": 0.7, "occurred_at": case.clock()}
    private = case.app.state.entity_service.create(
        context(case, case.agent_b["credential"]), "memory", {"content": "private target"},
        provenance, "agents." + case.agent_b["principal"]["slug"] + ".private",
    )
    async with case.mcp(case.agent_a["credential"]) as session:
        forbidden = await session.call_tool("cmh_create_memory_link", {"params": {
            "pinecone_vector_id": str(private["id"]),
        }})
    assert json.loads(body(forbidden)) == json.loads(body(missing))
    links = rows(case, "SELECT * FROM memory_links WHERE linked_event_ref='opaque historical event'")
    assert len(links) == 2
    for row in links:
        assert rows(case, "SELECT * FROM edges WHERE src_entity_id=:id AND type='about'",
                    id=row["id"])[0]["dst_entity_id"] == UUID(ids["memory"])


@pytest.mark.asyncio
async def test_T2B_8_directory_excludes_humans_and_includes_sponsor(compat_case):
    case, _ = compat_case
    async with case.mcp(case.agent_a["credential"]) as session:
        result = await session.call_tool("cmh_list_agents")
    assert not result.isError, body(result)
    entries = json.loads(body(result).split("FULL ORG CHART (JSON):", 1)[1])
    agents = {row["agent_id"]: row for row in entries}
    assert case.owner["id"] not in agents
    for agent, sponsor in ((case.agent_a, case.partner_a), (case.agent_b, case.partner_b)):
        row = agents[agent["principal"]["id"]]
        assert row["sponsor_slug"] == sponsor["slug"]
        assert row["tier"] == agent["principal"]["tier"]
        assert row["status"] == "active"


@pytest.fixture
def external_credential(identity):
    provisioned = identity.agent(identity.client_a, identity.partner_a, "external")
    principal, credential = provisioned["principal"], provisioned["credential"]
    # Deliberately retain an overbroad existing token after a role downgrade:
    # step 3 must constrain it, rather than only exercising missing-scope step 2.
    identity.tamper("UPDATE principals SET role='external',tier=1 WHERE id=:id",
                    id=principal["id"])
    return credential


@pytest.mark.asyncio
@pytest.mark.parametrize("name", WRITES)
async def test_T2B_9_external_every_write_denied_step_three(compat_case, external_credential, name):
    case, ids = compat_case
    async with case.mcp(external_credential) as session:
        result = await session.call_tool(name, sample(case, name, ids))
    assert denial(result, "TIER_FORBIDDEN")["step"] == 3


@pytest.mark.asyncio
async def test_T2B_10_exact_names_and_v1_required_types(compat_case):
    from jsonschema import Draft202012Validator

    case, ids = compat_case
    async with case.mcp(case.agent_a["credential"]) as session:
        listed = await session.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert tools.keys() == TOOLS.keys() | {"cmh_ping", "cmh_whoami", "cmh_check_access"}
    for name, definition in TOOLS.items():
        schema = tools[name].inputSchema
        Draft202012Validator(schema).validate(sample(case, name, ids))
        if definition["arguments"]:
            assert schema["required"] == ["params"]
            param = schema["properties"]["params"]
            model = schema["$defs"][param["$ref"].split("/")[-1]] if "$ref" in param else param
            assert set(model.get("required", [])) == {
                field["name"] for field in definition["fields"] if field["required"]
            }
            for field in definition["fields"]:
                assert field["name"] in model["properties"]
        else:
            assert schema.get("properties", {}) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(TOOLS))
async def test_T2B_11_each_call_has_one_sponsored_audit(compat_case, name):
    case, ids = compat_case
    async with case.mcp(case.agent_a["credential"]) as session:
        before = rows(case, "SELECT coalesce(max(seq),0) AS seq FROM audit_events")[0]["seq"]
        await session.call_tool(name, sample(case, name, ids))
        events = rows(case, "SELECT * FROM audit_events WHERE seq>:seq "
                      "AND operation!='mcp.transport'", seq=before)
    assert len(events) == 1
    assert str(events[0]["sponsor_id"]) == case.partner_a["id"]


@pytest.mark.asyncio
async def test_T2B_structured_legacy_lookup_and_v1_runtime_defaults(compat_case):
    case, ids = compat_case
    async with case.mcp(case.agent_a["credential"]) as session:
        old = await session.call_tool("cmh_get_structured", {
            "params": {"id": ids["legacy_structured"]},
        })
        assert not old.isError and json.loads(old.content[0].text)["id"] == ids["structured"]
        decision = await session.call_tool("cmh_log_decision", {"params": {
            "context": "default reversal", "made_by_agent": case.agent_a["principal"]["slug"],
            "decision_text": "keep the original reversible default",
        }})
        assert not decision.isError and decision.content[0].text.endswith("Reversible: True")
        created = await session.call_tool("cmh_create_session", {"params": {
            "agent_id": str(case.agent_a["principal"]["id"]),
        }})
        assert not created.isError
        assert created.content[0].text.endswith("Agent ID: " + str(case.agent_a["principal"]["id"]))
        listed = await session.call_tool("cmh_list_sessions", {"params": {
            "agent_id": str(case.agent_a["principal"]["id"]),
        }})
        assert not listed.isError and all(
            row["agent_id"] == str(case.agent_a["principal"]["id"])
            for row in json.loads(listed.content[0].text)
        )


@pytest.mark.no_app_operation(reason="Compatibility migration round trip and RLS/grant inspection.")
def test_T2B_12_compat_migration_round_trip(test_database, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from cmh.db.engine import normalize_database_url

    root = Path(__file__).parents[2]
    config = Config(str(root / "v2/alembic.ini"))
    monkeypatch.setenv("CMH_MIGRATE_DATABASE_URL", str(test_database))
    command.upgrade(config, "0004_compat")
    command.downgrade(config, "0003_memory_kernel")
    command.upgrade(config, "head")
    engine = create_engine(normalize_database_url(str(test_database)), hide_parameters=True)
    with engine.connect() as conn:
        for table in ("sessions", "messages"):
            assert conn.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid="
                                     "to_regclass(:name)"), {"name": table}).scalar() is True
            assert conn.execute(text("SELECT has_table_privilege('cmh_app',:name,'SELECT')"),
                                {"name": table}).scalar() is True
    engine.dispose()
