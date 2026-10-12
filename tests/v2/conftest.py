"""Dedicated PostgreSQL, test-body audit gate and Unix-only MCP transport."""

import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).parent))

pytest_plugins = ["identity_fixtures"]


class PrivateAdminEngine:
    def __init__(self, engine):
        self._engine = engine

    def __repr__(self):
        return "<administrative test engine; connection details redacted>"

    def __getattr__(self, name):
        return getattr(self._engine, name)


@pytest.fixture(scope="session")
def audit_admin(test_database):
    from audit_contract import service_profile
    from sqlalchemy import create_engine

    from cmh.db.engine import normalize_database_url

    engine = create_engine(normalize_database_url(test_database), hide_parameters=True)
    previous_profile = threading.getprofile()
    threading.setprofile(service_profile)
    yield PrivateAdminEngine(engine)
    threading.setprofile(previous_profile)
    engine.dispose()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    from audit_contract import BodyActivity, highest_seq, observe_body, validate_exemption

    engine = item.funcargs["audit_gate"]
    marker = item.get_closest_marker("no_app_operation")
    validate_exemption(marker, BodyActivity())
    before = highest_seq(engine)
    with observe_body() as activity:
        try:
            result = yield
        finally:
            validate_exemption(marker, activity)
            if marker is None:
                case = item.funcargs.get("identity")
                body_engine = case.engine if case is not None else None
                if body_engine is None and "client" in item.funcargs:
                    body_engine = item.funcargs["client"].app.state.engine
                after = highest_seq(engine)
                if body_engine is not None:
                    after = max(after, highest_seq(body_engine))
                if after <= before:
                    pytest.fail("4.1: test body wrote no new audit event; setup events never count")
    return result


@pytest.fixture(autouse=True)
def audit_gate(audit_admin, test_database, monkeypatch):
    monkeypatch.setenv("CMH_MIGRATE_DATABASE_URL", test_database)
    return audit_admin


def pytest_collection_modifyitems(items):
    def order(item):
        if item.name.startswith("test_1_9_bootstrap"):
            return 0
        if "migration_round_trip" in item.name or "migration_roundtrip" in item.name:
            return 2
        return 1
    items.sort(key=order)


class SensitiveTestValue(str):
    """Keep temporary tokens and database URLs out of pytest failure reports."""

    def __repr__(self):
        return "<redacted test credential>"


@pytest.fixture(scope="session")
def test_database():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from cmh.db.engine import guard_test_database, normalize_database_url

    url = os.environ.get("CMH_TEST_DATABASE_URL", "")
    guard_test_database(url, os.environ.get("CMH_DATABASE_URL"), os.environ.get("DATABASE_URL"))
    engine = create_engine(normalize_database_url(url), hide_parameters=True)
    with engine.begin() as conn:
        tables = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars().all()
        allowed = {
            "alembic_version", "principals", "users", "admin_sessions", "credentials",
            "credential_templates", "namespaces", "namespace_grants", "approvals",
            "audit_events", "notifications", "bootstrap_state",
            "entities", "entity_versions", "edges", "edge_types", "embeddings",
            "memories", "decisions", "knowledge", "org_states", "tasks", "experiments",
            "insights", "shared_contexts", "inbox_items", "memory_links",
            "orgs", "engagements", "projects", "notes",
        }
        assert set(tables) <= allowed, "Test database contains tables outside the v2 identity scope"
        # The spec requires a migration rebuild at the start of a run. During
        # that run, no fixture truncates or deletes any DENY/QUEUE audit rows.
        for name in sorted(allowed):
            conn.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
        # Table CASCADE removes triggers, not their standalone functions.
        for name in ("immutable_principal_slug", "require_human_user"):
            conn.execute(text(f"DROP FUNCTION IF EXISTS {name}()"))
        for extension in ("vector", "ltree", "pgcrypto"):
            conn.execute(text(f"DROP EXTENSION IF EXISTS {extension}"))
    config = Config(str(ROOT / "v2/alembic.ini"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CMH_DATABASE_URL", url)
        patch.setenv("CMH_MIGRATE_DATABASE_URL", url)
        command.upgrade(config, "head")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE alembic_version OWNER TO cmh_migrate"))
    private_url = SensitiveTestValue(url)
    private_url.runtime_role_url = SensitiveTestValue(os.environ["CMH_DATABASE_URL"])
    yield private_url
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE alembic_version OWNER TO cmh_migrate"))
    engine.dispose()


@pytest.fixture
def configured_env(monkeypatch, test_database):
    from sqlalchemy.engine import make_url

    from cmh.db.engine import normalize_database_url

    token = secrets.token_urlsafe(48)
    runtime_url = make_url(normalize_database_url(test_database.runtime_role_url)).set(
        database=make_url(normalize_database_url(test_database)).database,
    )
    monkeypatch.setenv("CMH_DATABASE_URL", runtime_url.render_as_string(hide_password=False))
    monkeypatch.setenv("CMH_PUBLIC_URL", "http://127.0.0.1:8008")
    monkeypatch.setenv("CMH_ENV", "test")
    monkeypatch.setenv("CMH_BOOTSTRAP_TOKEN", token)
    monkeypatch.setenv("CMH_ALLOWED_HOSTS", "")
    monkeypatch.setenv("CMH_EMBEDDING_PROVIDER", "fake")
    from sqlalchemy import event

    import cmh.app

    original = cmh.app.build_engine

    def factory(*args, **kwargs):
        engine = original(*args, **kwargs)
        if os.environ.get("CMH_ENV") == "test":
            @event.listens_for(engine, "connect")
            def app_role(connection, _record):
                with connection.cursor() as cursor:
                    cursor.execute("SET ROLE cmh_app")
        return engine
    monkeypatch.setattr(cmh.app, "build_engine", factory)
    return SensitiveTestValue(token)


@pytest.fixture
def valid_mcp_token(identity):
    return identity.owner_token["token"]


@pytest.fixture
def role_login_engine(test_database):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from cmh.db.engine import normalize_database_url

    url = make_url(normalize_database_url(test_database.runtime_role_url)).set(
        database=make_url(normalize_database_url(test_database)).database,
    )
    engine = create_engine(url, hide_parameters=True)
    yield PrivateAdminEngine(engine)
    engine.dispose()


@pytest.fixture
def client(configured_env):
    from fastapi.testclient import TestClient

    from cmh.app import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1") as instance:
        yield instance


@pytest.fixture
def unreachable_client(configured_env, monkeypatch):
    from fastapi.testclient import TestClient

    from cmh.app import create_app

    marker = SensitiveTestValue(secrets.token_urlsafe(32))
    monkeypatch.setenv(
        "CMH_DATABASE_URL", f"postgresql://unreachable:{marker}@127.0.0.1:1/unreachable",
    )
    with TestClient(create_app()) as instance:
        yield instance, marker


@pytest.fixture
def live_server(configured_env, tmp_path):
    import uvicorn

    from cmh.app import create_app

    sock = socket.socket(socket.AF_UNIX)
    path = str(tmp_path / "mcp.sock")
    sock.bind(path)
    server = uvicorn.Server(
        uvicorn.Config(create_app(), log_config=None, access_log=False, lifespan="on")
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        assert server.started, "ASGI server did not start"
        yield ("http://localhost/mcp", path)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), "ASGI server did not stop"
