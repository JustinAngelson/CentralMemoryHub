"""Phase 1 bearer/session perimeter contract, written before implementation.

Synthetic credentials are generated in memory, never placed in assertions,
error messages or command output. The existing Phase 0 contract is retained.
"""

import os
import secrets

import pytest


def require(condition, message):
    """Do not let pytest assertion rewriting expose credential material."""
    if not condition:
        raise AssertionError(message)


def test_1_1_missing_rest_bearer_is_audited(client):
    from sqlalchemy import text

    response = client.get("/api/whoami")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_MISSING"
    assert response.json()["outcome"] == "DENY"
    with client.app.state.engine.connect() as connection:
        event = connection.execute(text(
            "SELECT outcome, request_meta, decision_trace FROM audit_events ORDER BY seq DESC LIMIT 1"
        )).mappings().one()
        assert event["outcome"] == "DENY"
        assert event["request_meta"]["route"] == "/api/whoami"
        assert "AUTH_MISSING" in str(event["decision_trace"])


def test_1_2_missing_mcp_bearer_advertises_resource_metadata(client):
    response = client.post("/mcp", json={})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_MISSING"
    expected = (
        'Bearer resource_metadata="'
        + os.environ["CMH_PUBLIC_URL"]
        + '/.well-known/oauth-protected-resource"'
    )
    assert response.headers["www-authenticate"] == expected


def test_phase0_T0_5_replacement_wrong_mcp_token(client):
    response = client.post("/mcp", json={}, headers={
        "Authorization": "Bearer not-issued-test-token",
    })
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_INVALID"
    assert response.headers["www-authenticate"] == (
        'Bearer resource_metadata="' + os.environ["CMH_PUBLIC_URL"]
        + '/.well-known/oauth-protected-resource"'
    )


@pytest.mark.parametrize("authorization", [
    "", "Basic invalid", "Bearer", "Bearer invalid extra",
    "Bearer cmh_at_not-issued-in-phase1", "Bearer cmh_ak_unknown",
])
def test_1_3_unknown_or_malformed_bearer(client, authorization, caplog):
    response = client.get("/api/whoami", headers={"Authorization": authorization})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_INVALID"
    require(authorization not in caplog.text or not authorization, "Authorization was logged")


def test_1_7_query_credentials_are_ignored_and_redacted(client, configured_env, caplog):
    marker = secrets.token_urlsafe(32)
    response = client.get("/api/whoami", params={"key": marker})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_MISSING"
    require(marker not in caplog.text, "Query credential was logged")


def test_T1_1_health_reports_actual_application_role(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["db_role"] == "ok"
    with client.app.state.engine.connect() as connection:
        from sqlalchemy import text

        assert connection.execute(text("SELECT current_user")).scalar_one() == "cmh_app"


@pytest.mark.parametrize("path", ["/mcp", "/api/whoami"])
def test_T1_2_session_cookie_does_not_authenticate_bearer_surface(client, path):
    headers = {"Cookie": "cmh_session=synthetic-not-an-admin-session"}
    response = client.post(path, headers=headers, json={}) if path == "/mcp" else (
        client.get(path, headers=headers)
    )
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_MISSING"


def test_T1_3_bearer_does_not_authenticate_admin_surface(client, configured_env):
    response = client.get("/admin/api/principals", headers={
        "Authorization": "Bearer " + configured_env,
    })
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_MISSING"


def test_1_9_bootstrap_creates_owner_and_consumes_token(client, configured_env, audit_admin):
    from conftest import SensitiveTestValue

    password = SensitiveTestValue(secrets.token_urlsafe(24))
    headers = {
        "Authorization": "Bearer " + configured_env,
        "Origin": os.environ["CMH_PUBLIC_URL"],
    }
    body = {
        "display_name": "owner", "slug": "owner",
        "email": "owner@example.invalid", "password": password,
    }
    first = client.post("/admin/api/bootstrap", headers=headers, json=body)
    assert first.status_code == 201
    audit_admin._test_owner_password = password
    principal = first.json()["principal"]
    assert principal["slug"] == "owner"
    assert principal["kind"] == "human"
    assert principal["role"] == "owner"
    assert principal["tier"] == 4
    cookie = first.headers["set-cookie"].lower()
    require(
        all(flag in cookie for flag in ("secure", "httponly", "samesite=strict", "path=/admin")),
        "Admin session cookie security flags are incomplete",
    )
    second = client.post("/admin/api/bootstrap", headers=headers, json=body)
    assert second.status_code == 401
    assert second.json()["code"] == "AUTH_REVOKED"
    mcp = client.post("/mcp", headers=headers, json={})
    assert mcp.status_code == 401


def test_T1_4_bootstrap_without_origin_makes_no_change(client, configured_env):
    response = client.post("/admin/api/bootstrap", headers={
        "Authorization": "Bearer " + configured_env,
    }, json={
        "display_name": "owner", "slug": "owner",
        "email": "owner@example.invalid", "password": secrets.token_urlsafe(24),
    })
    assert response.status_code == 403
    assert response.json()["code"] == "ORIGIN_REJECTED"


def test_bootstrap_wrong_origin_is_rejected(client, configured_env):
    response = client.post("/admin/api/bootstrap", headers={
        "Authorization": "Bearer " + configured_env, "Origin": "https://foreign.example",
    }, json={
        "display_name": "owner", "slug": "owner",
        "email": "owner@example.invalid", "password": secrets.token_urlsafe(24),
    })
    assert response.status_code == 403
    assert response.json()["code"] == "ORIGIN_REJECTED"


@pytest.mark.parametrize("mode", ["dev", "prod"])
@pytest.mark.no_app_operation(reason="Startup superuser guard; no HTTP or service call.")
def test_T1_1_superuser_runtime_is_refused(configured_env, monkeypatch, mode):
    from cmh.app import create_app

    monkeypatch.setenv("CMH_ENV", mode)
    with pytest.raises(RuntimeError, match="(?i)(database role|db.role|superuser)"):
        create_app()


@pytest.mark.no_app_operation(reason="Seed command discovery only; no application operation.")
def test_expected_seed_command_exists():
    from importlib.util import find_spec

    assert find_spec("cmh.seed") is not None, "Phase 1 idempotent seed command is missing"
