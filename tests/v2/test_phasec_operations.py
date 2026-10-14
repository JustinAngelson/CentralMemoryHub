"""Native operator integrations use only the isolated test database."""
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from test_phase4a_apply import context


def test_C03_legacy_credentials_native_owner_scope_hash_only_idempotent(identity, capsys, caplog):
    from cmh.cutover.legacy import load_legacy

    case = identity
    secrets = {"MCP_BEARER_TOKEN": "fictional-mcp-token-not-a-real-secret",
               "API_KEY": "fictional-rest-token-not-a-real-secret"}
    result = load_legacy(case.service, context(case), secrets)
    assert {r["slug"]: r["status"] for r in result} == {
        "legacy-mcp": "created", "legacy-rest": "created"}
    assert all(r["status"] == "exists" for r in load_legacy(case.service, context(case), secrets))
    with case.service.engine.connect() as conn:
        rows = conn.execute(text("""SELECT p.slug,p.sponsor_id,c.scopes,c.kind,c.token_hash
          FROM principals p JOIN credentials c ON c.principal_id=p.id
          WHERE p.slug IN ('legacy-mcp','legacy-rest') AND c.kind='legacy_shared'""")).mappings().all()
        assert len(rows) == 2
        assert all(r["sponsor_id"] == case.owner["id"] for r in rows)
        rest = next(r for r in rows if r["slug"] == "legacy-rest")
        assert set(rest["scopes"]) == {"memory.read", "memory.write"}
        assert all("admin" not in scope for row in rows for scope in row["scopes"])
        for table in ("principals", "credentials", "audit_events", "notifications", "grants"):
            dumped = conn.execute(text(f"SELECT row_to_json(t)::text FROM {table} t")).scalars().all()
            assert all(value not in " ".join(dumped) for value in secrets.values())
    output = capsys.readouterr()
    assert all(value not in output.out + output.err + caplog.text for value in secrets.values())


def test_C04_native_export_is_readonly_excludes_imports_and_secret_values(identity, tmp_path):
    from cmh.cutover.exporting import export_records

    case = identity
    made = case.app.state.entities.create(context(case), "memory", {"content": "Fictional export"},
        {}, case.namespace)
    assert made.get("outcome") != "DENY"
    since = datetime.now(UTC) - timedelta(days=2)
    with case.service.engine.connect() as conn:
        # Fixture operation is audited above; export must perform only reads.
        rows, counts = export_records(conn, since, context(case))
    assert any(str(r["id"]) == str(made["id"]) for r in rows["entities"])
    assert all(not r.get("legacy_meta", {}).get("v1_id") for r in rows["entities"])
    serialized = json.dumps(rows, default=str)
    assert "token_hash" not in serialized and "password_hash" not in serialized
    assert "waitlist" not in rows and "waitlist" in counts
