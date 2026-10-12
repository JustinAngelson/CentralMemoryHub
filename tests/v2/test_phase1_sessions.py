"""Phase 1 additional gate rows T1.1–T1.15."""

import json
import secrets
from datetime import timedelta
from pathlib import Path

import pytest
from contract_helpers import denied
from identity_fixtures import require, token_hash
from sqlalchemy import create_engine, text


@pytest.mark.no_app_operation(reason="Startup table-owner guard; no request or service call.")
def test_T1_1_table_owner_runtime_refused(identity, role_login_engine, monkeypatch):
    import cmh.app

    identity.tamper("ALTER TABLE users OWNER TO cmh_app")
    monkeypatch.setenv("CMH_ENV", "dev")
    monkeypatch.setattr(cmh.app, "build_engine", lambda *_: role_login_engine)
    try:
        with pytest.raises(RuntimeError, match="(?i)(table.owner|owns.*table|database role)"):
            cmh.app.create_app()
    finally:
        identity.tamper("ALTER TABLE users OWNER TO cmh_migrate")
        # ALTER OWNER rewrites owner ACL entries. Restore the migration's
        # original application grants as well as ownership for later cases.
        identity.tamper("GRANT SELECT, INSERT, UPDATE, DELETE ON users TO cmh_app")


@pytest.mark.no_app_operation(reason="Startup audit-UPDATE privilege guard; no app operation.")
def test_T1_1_audit_update_privileged_runtime_refused(identity, role_login_engine, monkeypatch):
    import cmh.app

    identity.tamper("GRANT UPDATE ON audit_events TO cmh_app")
    monkeypatch.setenv("CMH_ENV", "prod")
    monkeypatch.setattr(cmh.app, "build_engine", lambda *_: role_login_engine)
    try:
        with pytest.raises(RuntimeError, match="(?i)(audit|database role)"):
            cmh.app.create_app()
    finally:
        identity.tamper("REVOKE UPDATE ON audit_events FROM cmh_app")


def test_T1_2_real_session_is_ignored_by_bearer_surfaces(identity):
    cookie_header = "; ".join(
        f"{cookie.name}={cookie.value}" for cookie in identity.owner_client.cookies.jar
        if cookie.path == "/admin"
    )
    require(bool(cookie_header), "No real admin session cookie available")
    for path in ("/api/whoami", "/mcp"):
        response = identity.owner_client.get(path, headers={"Cookie": cookie_header}) if (
            path.startswith("/api")
        ) else (
            identity.owner_client.post(path, json={}, headers={"Cookie": cookie_header})
        )
        denied(response, "AUTH_MISSING")


def test_T1_3_valid_bearer_ignored_by_admin(identity):
    from fastapi.testclient import TestClient

    client = TestClient(identity.app, base_url=identity.origin)
    response = client.get("/admin/api/principals", headers={
        "Authorization": "Bearer " + identity.owner_token["token"],
    })
    denied(response, "AUTH_MISSING")
    client.close()


@pytest.mark.parametrize("origin", [None, "https://foreign.example"])
def test_T1_4_unsafe_admin_origin_rejected_without_mutation(identity, origin):
    before = identity.sql("SELECT tier FROM principals WHERE id=:id",
                          id=identity.partner_a["id"])[0]["tier"]
    headers = {} if origin is None else {"Origin": origin}
    response = identity.owner_client.patch(
        f"/admin/api/principals/{identity.partner_a['id']}",
        headers=headers, json={"tier": 2},
    )
    denied(response, "ORIGIN_REJECTED")
    assert identity.sql("SELECT tier FROM principals WHERE id=:id",
                        id=identity.partner_a["id"])[0]["tier"] == before
    assert "ORIGIN_REJECTED" in json.dumps(identity.audit()[-1]["decision_trace"])


def test_T1_5_ten_failed_logins_lock_for_fifteen_minutes(identity, caplog):
    wrong = secrets.token_urlsafe(24)
    for _ in range(10):
        response = identity.request(identity.owner_client, "POST", "/admin/api/login", json={
            "email": "owner@example.invalid", "password": wrong,
        })
        assert response.status_code == 401
    denied(identity.request(identity.owner_client, "POST", "/admin/api/login", json={
        "email": "owner@example.invalid", "password": identity.password,
    }), "AUTH_LOCKED")
    identity.clock.advance(minutes=15, seconds=1)
    assert identity.request(identity.owner_client, "POST", "/admin/api/login", json={
        "email": "owner@example.invalid", "password": identity.password,
    }).status_code == 200
    require(wrong not in caplog.text, "Login password was logged")
    require(wrong not in json.dumps([dict(row) for row in identity.audit()], default=str),
            "Login password reached audit")


@pytest.mark.parametrize("expiry", ["idle", "absolute", "logout"])
def test_T1_6_session_expiration_and_revocation(identity, expiry):
    cookie_header = "; ".join(
        f"{cookie.name}={cookie.value}" for cookie in identity.owner_client.cookies.jar
        if cookie.path == "/admin"
    )
    require(bool(cookie_header), "No real admin session cookie available")
    if expiry == "idle":
        identity.clock.advance(hours=12, seconds=1)
    elif expiry == "absolute":
        identity.tamper(
            "UPDATE admin_sessions SET created_at=:old,last_seen_at=:now WHERE user_id IN "
            "(SELECT id FROM users WHERE principal_id=:id)",
            old=identity.clock() - timedelta(days=7, seconds=1), now=identity.clock(),
            id=identity.owner["id"],
        )
    else:
        assert identity.request(identity.owner_client, "POST",
                                "/admin/api/logout").status_code == 200
    # Replay the issued cookie even if logout/expiry removed it from the jar.
    response = identity.owner_client.get("/admin/api/principals",
                                        headers={"Cookie": cookie_header})
    denied(response, "AUTH_REVOKED" if expiry == "logout" else "AUTH_EXPIRED")


def test_T1_7_plaintext_only_in_issuance_response(identity, caplog):
    credential = identity.credential(identity.client_a, identity.partner_a, "personal-ai-client")
    token = credential["token"]
    row = identity.sql("SELECT * FROM credentials WHERE id=:id", id=credential["id"])[0]
    require(row["token_hash"] == token_hash(token), "Credential hash is incorrect")
    require(row["token_prefix"] == "cmh_pk_" + token[len("cmh_pk_"):len("cmh_pk_") + 4],
            "Credential prefix does not contain exactly four identifying characters")
    require(token not in json.dumps(dict(row), default=str), "Plaintext credential stored")
    require(token not in caplog.text, "Plaintext credential logged")
    require(token not in json.dumps([dict(r) for r in identity.body_audit()], default=str),
            "Plaintext credential reached audit")
    notifications = identity.sql("SELECT payload FROM notifications")
    require(token not in json.dumps([dict(r) for r in notifications], default=str),
            "Plaintext credential reached notification outbox")
    listed = identity.owner_client.get("/admin/api/credentials")
    assert listed.status_code == 200
    require(token not in listed.text, "Credential list re-disclosed plaintext")


def test_T1_8_owner_ai_client_stores_ceiling_reduced_scopes(identity):
    credential = identity.credential(identity.owner_client, identity.owner, "personal-ai-client")
    scopes = identity.sql("SELECT scopes FROM credentials WHERE id=:id",
                          id=credential["id"])[0]["scopes"]
    forbidden = {"grants.admin", "principals.admin", "credentials.admin",
                 "credentials.issue_sponsored"}
    assert not forbidden.intersection(scopes)
    assert not any(scope.startswith("policy.") for scope in scopes)
    assert identity.bearer(credential).json()["tier"] == 4


def test_T1_9_missing_namespace_does_not_leak_to_external(identity):
    namespace = "org.clients.example-mechanical"
    assert identity.request(identity.owner_client, "POST", "/admin/api/namespaces",
                            json={"path": namespace}).status_code == 201
    response = identity.request(identity.owner_client, "POST", "/admin/api/principals", json={
        "kind": "agent", "role": "external", "tier": 1,
        "slug": "external-test-" + secrets.token_hex(4), "display_name": "external_1",
        "sponsor_id": str(identity.owner["id"]), "template": "external-readonly",
        "namespaces": [namespace], "credential_name": "external-reader",
    })
    # Approval-required issuance never bypasses the residual queue.
    assert response.status_code == 202
    approval_id = response.json()["approval_id"]
    approved = identity.request(identity.owner_client, "POST",
                                f"/admin/api/approvals/{approval_id}/approve")
    assert approved.status_code == 200
    credential = approved.json()["credential"]
    grants = identity.sql("""
      SELECT n.path::text AS path,g.access FROM namespace_grants g
      JOIN namespaces n ON n.id=g.namespace_id WHERE g.principal_id=:id
    """, id=approved.json()["principal"]["id"])
    assert [dict(row) for row in grants] == [{"path": namespace, "access": "read"}]
    assert identity.check(credential, "memory.read", namespace).json()["outcome"] == "ALLOW"
    denied(identity.check(credential, "memory.read", "org.clients.ghost"), "NAMESPACE_FORBIDDEN")
    partner = identity.credential(identity.client_a, identity.partner_a, "personal-ai-client")
    denied(identity.check(partner, "memory.read", "org.clients.ghost"), "NAMESPACE_NOT_FOUND")


def test_T1_10_failed_auth_ip_limit_and_bounded_audit(identity):
    before = len(identity.audit())
    marker = "cmh_ak_" + secrets.token_urlsafe(32)
    headers = {"Authorization": "Bearer " + marker}
    for _ in range(30):
        assert identity.owner_client.get("/api/whoami", headers=headers).status_code == 401
    for _ in range(8):
        response = identity.owner_client.get("/api/whoami", headers=headers)
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0
    new = identity.audit()[before:]
    assert len(new) == 31
    summaries = [row for row in new if row["operation"] == "auth.rate_limit_summary"]
    assert len(summaries) == 1


@pytest.mark.no_app_operation(reason="Seed idempotence is infrastructure; no HTTP or service call.")
def test_T1_11_seed_idempotence(audit_admin):
    from cmh.seed import seed_database

    seed_database(audit_admin)
    tables = ("namespaces", "credential_templates")

    def snapshot():
        with audit_admin.connect() as connection:
            return {
                table: connection.execute(text(
                    f"SELECT row_to_json(t)::text FROM {table} t ORDER BY id"
                )).scalars().all() for table in tables
            }

    before = snapshot()
    seed_database(audit_admin)
    assert snapshot() == before


@pytest.mark.no_app_operation(reason="Migration downgrade/upgrade and grants inspection only.")
def test_T1_12_identity_migration_roundtrip(test_database, monkeypatch):
    from alembic import command
    from alembic.config import Config

    from cmh.db.engine import normalize_database_url

    monkeypatch.setenv("CMH_DATABASE_URL", test_database)
    monkeypatch.setenv("CMH_MIGRATE_DATABASE_URL", test_database)
    config = Config(str(Path(__file__).resolve().parents[2] / "v2/alembic.ini"))
    engine = create_engine(normalize_database_url(test_database), hide_parameters=True)
    # Run after operational tests: dropping identity tables mid-run would remove
    # their committed append-only evidence. No body fixture actors are created.
    command.downgrade(config, "0001")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT to_regclass('public.principals')")).scalar() is None
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT to_regclass('public.principals')")).scalar() is not None
        assert connection.execute(text(
            "SELECT has_table_privilege('cmh_app','audit_events','INSERT')"
        )).scalar() is True
        assert connection.execute(text(
            "SELECT has_table_privilege('cmh_app','audit_events','SELECT')"
        )).scalar() is True
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert connection.execute(text(
                "SELECT has_table_privilege('cmh_app','audit_events',:privilege)"
            ), {"privilege": privilege}).scalar() is False
    engine.dispose()


@pytest.mark.asyncio
async def test_T1_14_owner_ai_client_cannot_register_agent(identity):
    result, body = await identity.tool(identity.owner_token, "cmh_register_agent", {
        "slug": "agent-forbidden", "display_name": "agent_nix_test",
    })
    assert result.isError
    assert body["code"] == "AI_CLIENT_CEILING"
    assert body["step"] == 2


def test_T1_15_trusted_proxy_uses_two_from_right(identity, monkeypatch):
    from fastapi.testclient import TestClient

    from cmh.app import create_app

    monkeypatch.setenv("CMH_TRUSTED_PROXY_HOPS", "2")
    app = create_app()
    app.state.clock = identity.clock
    assert app.state.settings.trusted_proxy_hops == 2
    with TestClient(app, base_url=identity.origin) as client:
        response = client.get("/api/whoami", headers={
            "Authorization": "Bearer " + identity.owner_token["token"],
            "X-Forwarded-For": "198.51.100.199, 203.0.113.42, 192.0.2.10",
        })
    assert response.status_code == 200
    latest = identity.body_audit()[-1]
    assert latest["request_meta"]["client_ip"] == "203.0.113.42"
    assert latest["request_meta"]["client_ip"] != "198.51.100.199"


def test_rotation_old_credential_has_exact_twenty_four_hour_grace(identity):
    old = identity.owner_token
    response = identity.request(identity.owner_client, "POST",
                                f"/admin/api/credentials/{old['id']}/rotate")
    assert response.status_code == 201
    replacement = response.json()
    assert identity.bearer(old).status_code == 200
    assert identity.bearer(replacement).status_code == 200
    expires = identity.sql("SELECT expires_at FROM credentials WHERE id=:id",
                           id=old["id"])[0]["expires_at"]
    assert expires == identity.clock() + timedelta(hours=24)
    identity.clock.advance(hours=24, seconds=1)
    denied(identity.bearer(old), "AUTH_EXPIRED")
    assert identity.bearer(replacement).status_code == 200


def test_password_and_session_material_are_hash_only(identity):
    response = identity.request(identity.owner_client, "POST", "/admin/api/login", json={
        "email": "OWNER@EXAMPLE.INVALID", "password": identity.password,
    })
    assert response.status_code == 200
    user = identity.sql("SELECT * FROM users WHERE principal_id=:id",
                        id=identity.owner["id"])[0]
    require(user["password_hash"].startswith("$argon2id$"), "Password is not argon2id")
    require(identity.password not in json.dumps(dict(user), default=str), "Plaintext password stored")
    cookies = [c for c in identity.owner_client.cookies.jar if c.path == "/admin"]
    require(len(cookies) == 1, "Expected one scoped admin session cookie")
    sessions = identity.sql("SELECT * FROM admin_sessions WHERE user_id=:id", id=user["id"])
    require(cookies[0].value not in json.dumps([dict(row) for row in sessions], default=str),
            "Plaintext session ID stored")
    require(all(len(row["id_hash"]) in (32, 64) for row in sessions),
            "Session hash has unexpected length")
