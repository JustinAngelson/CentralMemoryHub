"""Gate 2B review regression tests, committed red before R4–R7 fixes."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from test_phase2_compat import compat_case  # noqa: F401
from test_phase2_kernel import context, rows

from cmh.auth.context import PrincipalContext
from cmh.mcp.compat_formats import project
from cmh.policy.evaluator import can_access, sponsor_ceiling
from cmh.services.compat import CompatService


def service(case):
    return CompatService(case.app.state.memory_service)


def create(case, tool, **payload):
    value = service(case).call(context(case), tool, {
        "namespace": case.namespace, **payload,
    })
    assert value.get("outcome") != "DENY", value
    return value


def test_R4_readable_set_matches_oracle_for_entire_fixture_world(identity):
    case = identity
    external = case.agent(case.owner_client, case.owner, "external-review")
    case.tamper("UPDATE principals SET role='external',tier=1 WHERE id=:id",
                id=external["principal"]["id"])
    # Include descendants under both kinds of private anchors and the A10 barrier.
    paths = [
        "agents." + case.agent_a["principal"]["slug"] + ".private.child",
        "people." + case.partner_a["slug"] + ".private.child",
        "org.finance.review-" + uuid4().hex,
    ]
    for path in paths:
        assert case.request(case.owner_client, "POST", "/admin/api/namespaces",
                            json={"path": path}).status_code == 201
    assert case.request(case.owner_client, "POST", "/admin/api/grants", json={
        "principal_id": case.agent_a["principal"]["id"],
        "namespace": "org.finance", "permission": "read",
    }).status_code == 201
    entities = case.app.state.entity_service
    for explicit_sponsor_grant in (False, True):
        if explicit_sponsor_grant:
            assert case.request(case.owner_client, "POST", "/admin/api/grants", json={
                "principal_id": str(case.partner_a["id"]),
                "namespace": "org.finance", "permission": "read",
            }).status_code == 201
        with entities.engine.begin() as conn:
            world = [dict(row) for row in conn.execute(text("SELECT * FROM principals")).mappings()]
            namespaces = list(conn.execute(text("SELECT id,path::text FROM namespaces")).mappings())
            for subject in world:
                expected = {str(n["id"]) for n in namespaces if can_access(
                    conn, subject, n["path"],
                ) and sponsor_ceiling(conn, subject, n["path"])}
                statements = []
                def count(*args):
                    statements.append(args[2])
                event.listen(entities.engine, "before_cursor_execute", count)
                try:
                    actual = set(entities.scope(conn, PrincipalContext(subject)))
                finally:
                    event.remove(entities.engine, "before_cursor_execute", count)
                assert actual == expected, subject["slug"]
                assert len(statements) <= 4
    # Successful authentication is itself audited within the test body.
    assert case.bearer(case.owner_token).status_code == 200


def test_R4_compat_update_query_count_constant_after_50_namespaces(compat_case):
    case, ids = compat_case
    adapter = service(case)
    counts = []
    for additional in (False, True):
        if additional:
            with case.admin.begin() as conn:
                conn.execute(text("""
                  INSERT INTO namespaces(id,path,mode,owner_principal_id)
                  SELECT gen_random_uuid(),CAST(:prefix || g AS ltree),'shared',:owner
                  FROM generate_series(1,50) g
                """), {"prefix": case.namespace + ".extra", "owner": case.owner["id"]})
        caller = context(case)
        statements = []
        def count(*args):
            statements.append(args[2])
        event.listen(case.engine, "before_cursor_execute", count)
        try:
            result = adapter.call(caller, "cmh_update_task", {
                "task_id": ids["task"], "status": "open",
            })
        finally:
            event.remove(case.engine, "before_cursor_execute", count)
        assert result.get("outcome") != "DENY", result
        counts.append(len(statements))
    assert counts[1] == counts[0], counts
    assert counts[0] < 80, counts


@pytest.mark.parametrize("tool,field,payload", [
    ("cmh_store_structured", "decision_text", {"gpt_role": "agent", "context_embedding": []}),
    ("cmh_log_decision", "decision_text", {"made_by_agent": "agent", "context": "example"}),
    ("cmh_create_task", "description", {"title": "example", "created_by_agent": "agent"}),
    ("cmh_create_org_state", "summary", {"entity": "example-mechanical", "type": "project",
                                      "status": "open", "last_updated_by": "agent"}),
])
def test_R6_body_once_in_entity_and_version(identity, tool, field, payload):
    body = "unique stored body with spaces " + uuid4().hex
    result = create(identity, tool, **payload, **{field: body})
    row = rows(identity, "SELECT to_jsonb(e) AS row FROM entities e WHERE id=:id",
               id=result["id"])[0]["row"]
    version = rows(identity, "SELECT snapshot FROM entity_versions WHERE entity_id=:id",
                   id=result["id"])[0]["snapshot"]
    assert json.dumps(row).count(body) == 1
    assert json.dumps(version).count(body) == 1
    assert set(row["legacy_meta"].get("v1_fields", {})) <= {
        "context_embedding", "related_documents",
    }


def test_R6_org_state_update_contains_only_v1_state_fields(identity):
    result = create(identity, "cmh_create_org_state", entity="Example Mechanical",
                    type="project", status="open", owner_agent=identity.agent_b["principal"]["slug"])
    updated = service(identity).call(context(identity), "cmh_update_org_state", {
        "entity_id": str(result["id"]), "status": "closed",
    })
    assert updated.get("outcome") != "DENY"
    state = updated["state"]
    assert set(state) <= {"entity", "type", "status", "summary", "owner_principal_id",
                         "last_updated_by", "important_dates", "linked_docs"}
    assert state["status"] == "closed"
    assert "entity_id" not in state and "owner_agent" not in state


@pytest.mark.parametrize("unresolved", [False, True])
def test_R6_target_view_uses_current_typed_slug_or_unresolved_text(identity, unresolved):
    target = "unknown target" if unresolved else identity.agent_b["principal"]["slug"]
    result = create(identity, "cmh_create_task", title="target contract",
                    assigned_to_agent=target)
    new_slug = "agent-renamed-" + uuid4().hex
    if not unresolved:
        identity.tamper("UPDATE principals SET slug=:slug WHERE id=:id",
                        slug=new_slug, id=identity.agent_b["principal"]["id"])
    output = service(identity).call(context(identity), "cmh_list_tasks",
                                    {"namespace": identity.namespace})
    view = project(next(row for row in output if row["id"] == result["id"]))
    assert view["assigned_to_agent"] == ("unknown target" if unresolved else new_slug)


@pytest.mark.parametrize("kind,tool,list_tool", [
    ("org_state", "cmh_create_org_state", "cmh_list_org_states"),
    ("knowledge", "cmh_store_knowledge", "cmh_search_knowledge"),
    ("decision", "cmh_log_decision", "cmh_list_decisions"),
    ("insight", "cmh_log_user_insight", "cmh_list_user_insights"),
])
def test_R7_v1_list_order(identity, kind, tool, list_tool):
    ids = []
    for n in (0, 1):
        payload = {
            "org_state": {"entity": f"state-{n}", "status": "open", "type": "project"},
            "knowledge": {"term": f"term-{n}", "relevance_score": 90 if n == 0 else 10},
            "decision": {"decision_text": f"decision-{n}",
                         "occurred_at": (identity.clock() - timedelta(days=n)).isoformat()},
            "insight": {"summary": f"insight-{n}",
                        "occurred_at": (identity.clock() - timedelta(days=n)).isoformat()},
        }[kind]
        ids.append(create(identity, tool, **payload)["id"])
        identity.clock.advance(seconds=1)
    if kind == "org_state":
        assert service(identity).call(context(identity), "cmh_update_org_state", {
            "entity_id": str(ids[0]), "status": "closed",
        }).get("outcome") != "DENY"
    result = service(identity).call(context(identity), list_tool, {"namespace": identity.namespace})
    assert [row["id"] for row in result] == ids


def test_R7_link_origin_case_insensitive_substring(identity):
    memory = create(identity, "cmh_store_structured", decision_text="linked body",
                    context_embedding=[], gpt_role=identity.agent_a["principal"]["slug"])
    link = create(identity, "cmh_create_memory_link", pinecone_vector_id=str(memory["id"]),
                  summary="link", origin_file_or_source="Reports/Example-MECHANICAL/Oct")
    result = service(identity).call(context(identity), "cmh_list_memory_links", {
        "namespace": identity.namespace, "origin_file_or_source": "mechanical",
    })
    assert [row["id"] for row in result] == [link["id"]]
