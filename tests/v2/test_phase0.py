"""Acceptance contract written before the Phase 0 implementation."""

import json
import logging
import secrets

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

EXPECTED = {
    "server": "cmh",
    "version": "2.0.0.dev0",
    "principal": "bootstrap",
    "env": "test",
}


def test_T0_1_missing_configuration_is_sanitized(monkeypatch):
    from cmh.app import create_app

    monkeypatch.delenv("CMH_DATABASE_URL", raising=False)
    monkeypatch.delenv("CMH_BOOTSTRAP_TOKEN", raising=False)
    monkeypatch.setenv("CMH_PUBLIC_URL", "https://configuration.example")
    monkeypatch.setenv("CMH_ENV", "test")
    with pytest.raises(RuntimeError) as error:
        create_app()
    assert "CMH_DATABASE_URL" in str(error.value)
    assert "CMH_BOOTSTRAP_TOKEN" in str(error.value)
    assert "postgresql://" not in str(error.value)
    assert "input_value" not in str(error.value)


def test_T0_2_health(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == EXPECTED["version"]
    assert body["env"] == "test"
    assert body["database"] == "ok"
    assert body["extensions"] == {"vector": True, "ltree": True, "pgcrypto": True}


def test_T0_3_unreachable_database(configured_env, monkeypatch):
    from fastapi.testclient import TestClient

    from cmh.app import create_app

    marker = secrets.token_urlsafe(32)
    monkeypatch.setenv(
        "CMH_DATABASE_URL", f"postgresql://unreachable:{marker}@127.0.0.1:1/unreachable"
    )
    with TestClient(create_app()) as instance:
        response = instance.get("/healthz")
    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"
    assert marker not in response.text
    assert "Traceback" not in response.text
    assert "OperationalError" not in response.text


def test_T0_4_missing_mcp_auth(client):
    response = client.post("/mcp", json={})
    assert response.status_code == 401
    assert response.json() == {"code": "AUTH_MISSING"}
    assert response.headers["www-authenticate"] == 'Bearer realm="cmh"'


def test_T0_5_wrong_mcp_auth(client):
    response = client.post("/mcp", headers={"Authorization": "Bearer wrong"}, json={})
    assert response.status_code == 401
    assert response.json() == {"code": "AUTH_INVALID"}
    assert response.headers["www-authenticate"] == 'Bearer realm="cmh"'


def test_T0_6_logs_redact_secrets(client, configured_env, caplog):
    invalid = secrets.token_urlsafe(48)
    field_marker = secrets.token_urlsafe(24)
    caplog.set_level(logging.INFO)
    headers = {
        "Authorization": f"Bearer {configured_env}",
        "Accept": "application/json, text/event-stream",
    }
    client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                   "clientInfo": {"name": "phase0-tests", "version": "0"}},
    })
    client.post("/mcp", headers={"Authorization": f"Bearer {invalid}"}, json={})
    logging.getLogger("cmh").info("redaction_probe", extra={
        "api_key": field_marker,
        "nested": {"Password": field_marker, "access_TOKEN": field_marker,
                   "client_secret": field_marker, "safe": "visible"},
    })
    assert caplog.records
    serialized = caplog.text + "\n".join(
        json.dumps(record.__dict__, default=str) for record in caplog.records
    )
    for secret in (configured_env, invalid, field_marker):
        assert secret not in serialized
    assert f"Authorization: Bearer {configured_env}" not in serialized
    assert all(getattr(record, "requestID", None) for record in caplog.records)
    probe = next(record for record in caplog.records if record.getMessage() == "redaction_probe")
    assert probe.api_key == "[REDACTED]"
    assert probe.nested["safe"] == "visible"
    assert probe.nested["Password"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_T0_7_real_mcp_client(live_server, configured_env):
    async with (
        httpx.AsyncClient(headers={"Authorization": f"Bearer {configured_env}"}) as http,
        streamable_http_client(live_server, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        initialized = await session.initialize()
        assert initialized.serverInfo.name == "cmh"
        tools = await session.list_tools()
        assert [tool.name for tool in tools.tools] == ["cmh_ping"]
        assert tools.tools[0].inputSchema.get("properties", {}) == {}
        result = await session.call_tool("cmh_ping", {})
        assert not result.isError
        assert json.loads(result.content[0].text) == EXPECTED


def test_T0_8_exact_endpoint(client, configured_env):
    headers = {"Authorization": f"Bearer {configured_env}"}
    canonical = client.post("/mcp", headers=headers, json={}, follow_redirects=False)
    assert canonical.status_code not in (301, 302, 307, 308, 401, 404)
    assert client.post("/mcp/mcp", headers=headers, json={}).status_code == 404
    assert client.post("/mcp/mcp", json={}).status_code == 404


@pytest.mark.asyncio
async def test_T0_9_identity_cannot_be_supplied(live_server, configured_env):
    async with (
        httpx.AsyncClient(headers={"Authorization": f"Bearer {configured_env}"}) as http,
        streamable_http_client(live_server, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        for field in ("principal", "agent_id"):
            result = await session.call_tool("cmh_ping", {field: "attacker"})
            assert result.isError or json.loads(result.content[0].text) == EXPECTED
        normal = await session.call_tool("cmh_ping", {})
        assert json.loads(normal.content[0].text)["principal"] == "bootstrap"


def test_T0_10_database_guard():
    from cmh.db.engine import TestDatabaseIsolationError, guard_test_database

    dev = "postgresql://user:never-log@localhost:5432/cmh_v2_dev"
    v1 = "postgresql://user:never-log@localhost:5432/v1"
    for url in (dev, v1):
        with pytest.raises(TestDatabaseIsolationError) as error:
            guard_test_database(url, dev, v1)
        assert "never-log" not in str(error.value)
    alias = "postgresql+psycopg://other:different@127.0.0.1:5432/cmh_v2_dev"
    with pytest.raises(TestDatabaseIsolationError):
        guard_test_database(alias, dev, v1)
    guard_test_database("postgresql://user:pass@localhost:5432/cmh_v2_test", dev, v1)
    with pytest.raises(TestDatabaseIsolationError):
        guard_test_database("", dev, v1)


def test_T0_11_migration_round_trip(test_database, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from cmh.db.engine import normalize_database_url

    monkeypatch.setenv("CMH_DATABASE_URL", test_database)
    config = Config(str(Path(__file__).resolve().parents[2] / "v2/alembic.ini"))
    engine = create_engine(normalize_database_url(test_database))
    try:
        command.downgrade(config, "base")
        with engine.connect() as conn:
            assert conn.execute(text(
                "SELECT count(*) FROM pg_extension WHERE extname IN ('vector','ltree','pgcrypto')"
            )).scalar_one() == 0
        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert conn.execute(text(
                "SELECT count(*) FROM pg_extension WHERE extname IN ('vector','ltree','pgcrypto')"
            )).scalar_one() == 3
            assert conn.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )).scalars().all() == ["alembic_version"]
    finally:
        engine.dispose()


@pytest.mark.parametrize("value", ["Basic wrong", "Bearer", "Bearer wrong extra", ""])
def test_malformed_auth_is_rejected(client, value):
    response = client.post("/mcp", headers={"Authorization": value}, json={})
    assert response.status_code == 401
    assert response.json() == {"code": "AUTH_INVALID"}


def test_other_credentials_do_not_authenticate(client, configured_env):
    response = client.post(
        f"/mcp?key={configured_env}",
        headers={"X-API-KEY": configured_env, "Mcp-Session-Id": configured_env}, json={}
    )
    assert response.status_code == 401
    assert response.json() == {"code": "AUTH_MISSING"}


@pytest.mark.parametrize("base", [
    "https://example.test/", "https://example.test/mcp",
    "https://example.test?key=no", "https://user:password@example.test",
])
def test_public_url_must_be_a_base(configured_env, monkeypatch, base):
    from cmh.app import create_app

    monkeypatch.setenv("CMH_PUBLIC_URL", base)
    with pytest.raises(RuntimeError) as error:
        create_app()
    assert "CMH_PUBLIC_URL" in str(error.value)
    assert base not in str(error.value)


def test_request_id_and_host_protection(client, configured_env):
    response = client.get("/healthz")
    assert response.headers["X-Request-ID"]
    response = client.post("/mcp", headers={
        "Authorization": f"Bearer {configured_env}", "Host": "attacker.example",
        "Accept": "application/json, text/event-stream",
    }, json={})
    assert response.status_code == 421


def test_uvicorn_access_logs_stay_disabled(configured_env):
    """Factory logging must not re-enable URL/query-string access logs."""
    from cmh.app import create_app

    create_app()
    assert logging.getLogger("uvicorn.access").disabled


@pytest.mark.parametrize("host,status", [
    ("phase0-dev.test", 200),
    ("phase0-dev.test:443", 200),
    ("127.0.0.1", 200),
    ("127.0.0.1:8008", 200),
    ("localhost", 200),
    ("localhost:8008", 200),
    ("api.example-mechanical.test", 421),
    ("legacy.example-mechanical.test", 421),
])
def test_development_mcp_host_allowlist(configured_env, monkeypatch, host, status):
    from fastapi.testclient import TestClient

    from cmh.app import create_app

    monkeypatch.setenv("CMH_PUBLIC_URL", "https://phase0-dev.test")
    monkeypatch.setenv("CMH_ALLOWED_HOSTS", "phase0-dev.test,127.0.0.1,localhost")
    with TestClient(create_app()) as instance:
        response = instance.post("/mcp", headers={
            "Authorization": f"Bearer {configured_env}",
            "Host": host,
            "Accept": "application/json, text/event-stream",
        }, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "host-regression", "version": "1"},
            },
        })
    assert response.status_code == status
