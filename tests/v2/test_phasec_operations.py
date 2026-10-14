"""Native operator integrations use only the isolated test database."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from test_phase4a_apply import context, import_case, reviewed_import  # noqa: F401 — fixtures


def test_C03_legacy_credentials_native_owner_scope_hash_only_idempotent(identity, capsys, caplog):
    from cmh.cutover.legacy import load_legacy
    from cmh.services.accounts import digest

    case = identity
    service = case.app.state.identity_service
    secrets = {"MCP_BEARER_TOKEN": "fictional-mcp-token-not-a-real-secret",
               "API_KEY": "fictional-rest-token-not-a-real-secret"}
    result = load_legacy(service, context(case), secrets)
    assert {r["slug"]: r["status"] for r in result} == {
        "legacy-mcp": "created", "legacy-rest": "created"}
    assert all(r["status"] == "exists" for r in load_legacy(service, context(case), secrets))
    with service.engine.connect() as conn:
        rows = conn.execute(text("""SELECT p.slug,p.sponsor_id,c.scopes,c.kind,c.token_hash
          FROM principals p JOIN credentials c ON c.principal_id=p.id
          WHERE p.slug IN ('legacy-mcp','legacy-rest') AND c.kind='legacy_shared'
          AND c.token_hash=ANY(:hashes)"""),
          {"hashes": [digest(value) for value in secrets.values()]}).mappings().all()
        assert len(rows) == 2
        assert all(str(r["sponsor_id"]) == str(case.owner["id"]) for r in rows)
        rest = next(r for r in rows if r["slug"] == "legacy-rest")
        assert set(rest["scopes"]) == {"memory.read", "memory.write"}
        assert all("admin" not in scope for row in rows for scope in row["scopes"])
        grants = conn.execute(text("""SELECT p.slug,n.path::text,g.access FROM namespace_grants g
          JOIN principals p ON p.id=g.principal_id JOIN namespaces n ON n.id=g.namespace_id
          WHERE p.slug IN ('legacy-mcp','legacy-rest')""")).all()
        assert set(grants) == {("legacy-mcp", "org", "write"),
                               ("legacy-mcp", "org.clients", "read"),
                               ("legacy-rest", "org", "write")}
        for table in ("principals", "credentials", "audit_events", "notifications", "namespace_grants"):
            dumped = conn.execute(text(f"SELECT row_to_json(t)::text FROM {table} t")).scalars().all()
            assert all(value not in " ".join(dumped) for value in secrets.values())
    output = capsys.readouterr()
    assert all(value not in output.out + output.err + caplog.text for value in secrets.values())


def test_C04_native_export_is_readonly_excludes_unchanged_imports_and_secret_values(identity, tmp_path):
    from cmh.cutover.exporting import export_records

    case = identity
    made = case.app.state.memory_service.store(context(case),
        {"content": "Fictional export", "namespace": case.namespace}, compatibility=True)
    assert made.get("outcome") != "DENY"
    since = datetime.now(UTC) - timedelta(days=2)
    with case.app.state.engine.connect() as conn:
        # Fixture operation is audited above; export must perform only reads.
        rows, counts = export_records(conn, since, context(case))
    assert any(str(r["id"]) == str(made["id"]) for r in rows["entities"])
    assert not next(r for r in rows["entities"] if str(r["id"]) == str(made["id"]))["legacy_meta"].get("v1_id")
    serialized = json.dumps(rows, default=str)
    assert "token_hash" not in serialized and "password_hash" not in serialized
    assert "waitlist" in rows and counts["waitlist"] == len(rows["waitlist"])
    def imported(conn):
        case.app.state.entities.scope(conn, context(case))
        conn.execute(text("""UPDATE entities SET legacy_meta='{"v1_table":"unstructured_data",
          "v1_id":"fictional-source"}' WHERE id=:id"""), {"id": made["id"]})
    service = case.app.state.identity_service
    service.perform(context(case), "memory.write", case.namespace, change=imported)
    with case.app.state.engine.connect() as conn:
        rows, _ = export_records(conn, since, context(case))
        assert not any(str(r["id"]) == str(made["id"]) for r in rows["entities"])
        with pytest.raises(Exception, match="read.only"):
            conn.execute(text("CREATE TABLE public.__export_must_refuse_write(id integer)"))


def test_CR1_export_includes_changed_import_current_snapshot_with_v1_id(identity):
    from cmh.cutover.exporting import export_records

    case = identity
    made = case.app.state.memory_service.store(context(case),
        {"content": "Original imported text", "namespace": case.namespace}, compatibility=True)
    legacy_id = "fictional-source-" + str(made["id"])

    def imported(conn):
        case.app.state.entities.scope(conn, context(case))
        conn.execute(text("""UPDATE entities SET legacy_meta=CAST(:meta AS jsonb) WHERE id=:id"""),
                     {"id": made["id"], "meta": json.dumps(
                         {"v1_table": "unstructured_data", "v1_id": legacy_id})})

    case.app.state.identity_service.perform(
        context(case), "memory.write", case.namespace, change=imported)
    case.clock.advance(seconds=1)
    since = case.clock()
    case.clock.advance(seconds=1)
    changed = case.app.state.entity_service.update(
        context(case), made["id"], {"content": "Updated imported text"})
    assert changed.get("outcome") != "DENY"
    with case.app.state.engine.connect() as conn:
        records, counts = export_records(conn, since, context(case))
    selected = [r for r in records["entities"] if str(r["id"]) == str(made["id"])]
    assert len(selected) == 1
    assert selected[0]["legacy_meta"]["v1_id"] == legacy_id
    assert selected[0]["current_version_snapshot"]["content"] == "Updated imported text"
    assert selected[0]["current_version"] == 2
    assert counts["entities"] >= 1
    with case.app.state.engine.connect() as conn:
        after_boundary, _ = export_records(conn, case.clock(), context(case))
    assert not any(str(r["id"]) == str(made["id"]) for r in after_boundary["entities"])


def test_CR1_waitlist_exports_new_rows_not_old_and_preserves_email_privately(identity, capsys, caplog):
    from cmh.cutover.exporting import export_records

    case = identity
    since = case.clock()
    addresses = ["old@example.invalid", "new@example.invalid", "imported@example.invalid"]

    def signup(conn):
        for address, offset, meta in zip(addresses, (-1, 1, 1), ({}, {}, {"v1_id": "example"})):
            conn.execute(text("""INSERT INTO waitlist(email,source,created_at,legacy_meta)
              VALUES(:email,'test',:created,CAST(:meta AS jsonb))"""),
              {"email": address, "created": since + timedelta(seconds=offset),
               "meta": json.dumps(meta)})

    case.app.state.identity_service.perform(
        context(case), "memory.write", case.namespace, change=signup)
    with case.app.state.engine.connect() as conn:
        records, counts = export_records(conn, since, context(case))
    exported = {r["email"] for r in records["waitlist"]}
    assert addresses[0] not in exported
    assert set(addresses[1:]) <= exported
    assert counts["waitlist"] == len(records["waitlist"])
    captured = capsys.readouterr()
    assert all(address not in captured.out + captured.err + caplog.text for address in addresses)


@pytest.mark.anyio
async def test_C05_smoke_real_app_no_token_output(identity, capsys):
    from fastapi.testclient import TestClient
    from test_phasec_tooling import script
    anonymous = TestClient(identity.app, base_url=identity.origin)

    class Adapter:
        async def get(self, url):
            return anonymous.get(url)

        async def post(self, url, **kwargs):
            return anonymous.post(url, **kwargs)

    origin = identity.app.state.settings.public_url
    result = await script("check_production").check_url(origin, client=Adapter())
    assert result["ok"], result
    assert not capsys.readouterr().out
    anonymous.close()


def test_C02_new_row_without_reviewed_namespace_refuses_apply(reviewed_import):  # noqa: F811
    runner, _, source, directory = reviewed_import
    added = {**source["tables"]["unstructured_data"][0], "id": "unreviewed-new-row"}
    source["tables"]["unstructured_data"].append(added)
    source["counts"]["unstructured_data"] += 1
    with pytest.raises(ValueError, match="reviewed namespace"):
        runner.apply(source, directory)
