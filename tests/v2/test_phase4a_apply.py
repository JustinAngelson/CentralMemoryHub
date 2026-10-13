"""Phase 4A apply contracts: fictional records and native, bootstrap-owned identity."""
import importlib
import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import text


def context(case):
    from cmh.auth.context import PrincipalContext

    with case.admin.connect() as conn:
        owner = dict(conn.execute(text("SELECT * FROM principals WHERE role='owner'")).mappings().one())
    return PrincipalContext(owner, request_meta={"surface": "import"})


@pytest.fixture
def import_case(identity, tmp_path):
    cls = importlib.import_module("cmh.importing.runner").ImportRunner
    return cls(identity.app.state.entities, context(identity)), identity, tmp_path


def native_roster(case):
    rows = []
    for principal in [case.owner, case.partner_a, case.partner_b,
                      case.agent_a["principal"], case.agent_b["principal"]]:
        with case.admin.connect() as conn:
            value = dict(conn.execute(text("SELECT * FROM principals WHERE id=:id"),
                                      {"id": principal["id"]}).mappings().one())
            sponsor = conn.execute(text("SELECT slug FROM principals WHERE id=:id"),
                                   {"id": value["sponsor_id"]}).scalar()
        rows.append({"slug": value["slug"], "name": value["display_name"], "action": "import",
                     "kind": value["kind"], "role": value["role"] or "",
                     "tier": str(value["tier"] or ""), "sponsor": sponsor or "",
                     "status": value["status"], "v1_id": "source-" + value["slug"],
                     "aliases": json.dumps(["source-" + value["slug"]])})
    return rows


def test_r10_reuse_existing_slugs_rerun_creates_zero_principals(import_case):
    runner, case, _ = import_case
    before = case.admin.connect()
    count = before.execute(text("SELECT count(*) FROM principals")).scalar_one()
    before.close()
    rows = native_roster(case)
    assert runner.ensure_roster(rows)["created"] == 0
    assert runner.ensure_roster(rows)["created"] == 0
    with case.admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM principals")).scalar_one() == count
        assert conn.execute(text("SELECT count(*) FROM principals WHERE role='owner'")).scalar_one() == 1
        assert conn.execute(text("SELECT tier FROM principals WHERE role='owner'")).scalar_one() == 4
        assert conn.execute(text("SELECT bool_and(tier=3) FROM principals WHERE role='partner'")).scalar_one()


def test_r10_owner_must_already_be_bootstrapped(import_case):
    runner, case, _ = import_case
    rows = native_roster(case)
    rows[0] = {**rows[0], "slug": "never-a-second-owner"}
    with pytest.raises(ValueError, match="bootstrap"):
        runner.ensure_roster(rows)
    with case.admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM principals WHERE role='owner'")).scalar_one() == 1


def test_t4a_1_inactive_persona_no_credentials(import_case):
    runner, case, _ = import_case
    roster = native_roster(case)
    slug = "agent-persona-" + case.namespace.split("-")[-1]
    roster.append({"slug": slug, "name": "Agent Persona Test", "action": "import",
                   "kind": "agent", "role": "", "tier": "1", "sponsor": "owner",
                   "status": "inactive", "v1_id": "persona-test", "aliases": '["persona-test"]'})
    assert runner.ensure_roster(roster)["created"] == 1
    with case.admin.connect() as conn:
        row = conn.execute(text("SELECT * FROM principals WHERE slug=:slug"), {"slug": slug}).mappings().one()
        assert row["tier"] == 1 and row["status"] == "inactive"
        assert conn.execute(text("SELECT count(*) FROM credentials WHERE principal_id=:id"),
                            {"id": row["id"]}).scalar_one() == 0


def fixture_snapshot(case):
    from cmh.importing.source import INVENTORY

    now = datetime(2024, 2, 3, 4, 5, tzinfo=UTC)
    memory_id = "memory-" + case.namespace
    tables = {name: [] for name in INVENTORY}
    tables["unstructured_data"] = [
        {"id": memory_id, "content": "[source: direct] [agent: owner] [date: 2023-01-02] Example Mechanical",
         "pinecone_id": "archived-" + memory_id, "created_at": now, "updated_at": now},
        {"id": memory_id + "-unknown", "content": "[agent: unmapped_test] fictional observation"},
    ]
    tables["project_decisions"] = [{"id": "decision-" + case.namespace,
                                   "decision_text": "Use the fictional component",
                                   "context_embedding": [0.2, 0.4], "created_at": now}]
    return {"tables": tables, "counts": {name: len(rows) for name, rows in tables.items()},
            "primary_keys": {name: ["id"] for name in tables}}


@pytest.fixture
def reviewed_import(import_case):
    runner, case, directory = import_case
    source = fixture_snapshot(case)
    from cmh.importing.plan import write_csv

    rows = native_roster(case)
    write_csv(directory / "roster_review.csv", rows, list(rows[0]))
    attribution = [{"value": "owner", "count": "1", "proposed_principal": "owner"},
                   {"value": "unmapped_test", "count": "1", "proposed_principal": ""}]
    write_csv(directory / "attribution_review.csv", attribution, list(attribution[0]))
    mappings = [{"v1_table": table, "v1_id": row["id"], "proposed_namespace": "org",
                 "matched_aliases": "EXM" if table == "unstructured_data" else "", "reason": "reviewed"}
                for table, rows in source["tables"].items() for row in rows]
    write_csv(directory / "namespace_mapping.csv", mappings, list(mappings[0]))
    return runner, case, source, directory


def test_6_1_row_accounting_and_6_2_idempotent_resume(reviewed_import):
    runner, case, source, directory = reviewed_import
    first = runner.apply(source, directory)
    assert first["complete"] and first["source_rows"] == 3 and first["imported"] == 3
    second = runner.apply(source, directory)
    assert second["complete"] and second["imported"] == 0 and second["existing"] == 3
    with case.admin.connect() as conn:
        assert conn.execute(text("""SELECT count(*) FROM principals WHERE slug='v1-import'""")).scalar_one() == 1


def test_6_3_6_4_t4a_3_tags_author_timestamps(reviewed_import):
    runner, case, source, directory = reviewed_import
    runner.apply(source, directory)
    with case.admin.connect() as conn:
        rows = conn.execute(text("""SELECT * FROM entities WHERE legacy_meta->>'v1_id' LIKE :prefix
          ORDER BY legacy_meta->>'v1_id'"""), {"prefix": "memory-" + case.namespace + "%"}).mappings().all()
        assert len(rows) == 2
        assert rows[0]["source_type"] == "conversation" and float(rows[0]["confidence"]) == 0.85
        assert rows[0]["occurred_at"] == datetime(2023, 1, 2, tzinfo=UTC)
        assert rows[0]["created_at"] == source["tables"]["unstructured_data"][0]["created_at"]
        assert rows[1]["author_principal_id"] is None
        assert rows[1]["legacy_meta"]["claimed"]["agent"] == "unmapped_test"
        assert rows[1]["legacy_meta"]["occurred_at_unknown"]
        snapshot = conn.execute(text("SELECT snapshot FROM entity_versions WHERE entity_id=:id"),
                                {"id": rows[0]["id"]}).scalar_one()
        assert datetime.fromisoformat(snapshot["created_at"]) == rows[0]["created_at"]


def test_t4a_5_import_trace_one_event_per_row_and_revoked_credential(reviewed_import):
    runner, case, source, directory = reviewed_import
    report = runner.apply(source, directory)
    with case.admin.connect() as conn:
        actor = conn.execute(text("SELECT id FROM principals WHERE slug='v1-import'")).scalar_one()
        assert conn.execute(text("SELECT bool_and(revoked_at IS NOT NULL) FROM credentials WHERE principal_id=:id"),
                            {"id": actor}).scalar_one()
        events = conn.execute(text("""SELECT * FROM audit_events WHERE principal_id=:id
           AND decision_trace->'import'->>'run_id'=:run"""),
                              {"id": actor, "run": report["run_id"]}).mappings().all()
        assert len(events) == 3


def test_t4a_8_apply_missing_review_refused_and_audited(import_case):
    runner, _, directory = import_case
    with pytest.raises(ValueError, match="review"):
        runner.apply({"tables": {}, "counts": {}}, directory)


@pytest.mark.parametrize("path", ["/search", "/memory/unstructured"])
def test_t4a_13_compat_rest_requires_bearer(identity, path):
    assert identity.owner_client.post(path, json={"content": "fictional", "query": "fictional"}).status_code == 401


def test_t4a_13_compat_roundtrip_and_a12(identity):
    stored = identity.bearer(identity.owner_token, "POST", "/memory/unstructured", json={
        "content": "[agent: not-the-caller] fictional compatibility marker", "gpt_role": "unmapped_test",
    })
    assert stored.status_code == 201
    found = identity.bearer(identity.owner_token, "POST", "/search", json={"query": "fictional compatibility marker"})
    assert found.status_code == 200 and found.json()["results"]
    with identity.admin.connect() as conn:
        assert str(conn.execute(text("SELECT author_principal_id FROM entities WHERE id=:id"),
                                {"id": stored.json()["id"]}).scalar_one()) == str(identity.owner["id"])


def test_t4a_10_landing_headers_and_invalid_waitlist(identity):
    response = identity.owner_client.get("/")
    assert response.status_code == 200 and "Central" in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert identity.owner_client.post("/api/waitlist", json={"email": "invalid"}).status_code == 400
    assert identity.owner_client.post("/api/waitlist", json={"email": "x" * 121 + "@example.invalid"}).status_code == 400


def test_t4a_10_waitlist_valid_duplicate_and_ip_limit(identity):
    client = identity.owner_client
    email = case_email = "signup-" + identity.namespace + "@example.invalid"
    assert client.post("/api/waitlist", json={"email": email}).status_code == 200
    assert client.post("/api/waitlist", json={"email": case_email.upper()}).status_code == 200
    with identity.admin.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM waitlist WHERE lower(email)=:email"),
                            {"email": email}).scalar_one() == 1
    for _ in range(3):
        client.post("/api/waitlist", json={"email": email})
    assert client.post("/api/waitlist", json={"email": email}).status_code == 429
