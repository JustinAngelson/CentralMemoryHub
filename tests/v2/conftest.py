"""Phase 0 fixtures: dedicated PostgreSQL and a real TCP ASGI server."""

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


@pytest.fixture(scope="session")
def test_database():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from cmh.db.engine import guard_test_database, normalize_database_url

    url = os.environ.get("CMH_TEST_DATABASE_URL", "")
    guard_test_database(url, os.environ.get("CMH_DATABASE_URL"), os.environ.get("DATABASE_URL"))
    engine = create_engine(normalize_database_url(url))
    with engine.begin() as conn:
        tables = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars().all()
        assert set(tables) <= {"alembic_version"}, "Test database contains non-Phase-0 tables"
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        for extension in ("vector", "ltree", "pgcrypto"):
            conn.execute(text(f"DROP EXTENSION IF EXISTS {extension}"))
    config = Config(str(ROOT / "v2/alembic.ini"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("CMH_DATABASE_URL", url)
        patch.setenv("CMH_MIGRATE_DATABASE_URL", url)
        command.upgrade(config, "head")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE alembic_version OWNER TO cmh_migrate"))
    yield url
    engine.dispose()


@pytest.fixture
def configured_env(monkeypatch, test_database):
    token = secrets.token_urlsafe(48)
    monkeypatch.setenv("CMH_DATABASE_URL", test_database)
    monkeypatch.setenv("CMH_PUBLIC_URL", "http://127.0.0.1:8008")
    monkeypatch.setenv("CMH_ENV", "test")
    monkeypatch.setenv("CMH_BOOTSTRAP_TOKEN", token)
    monkeypatch.setenv("CMH_ALLOWED_HOSTS", "")
    return token


@pytest.fixture
def client(configured_env):
    from fastapi.testclient import TestClient

    from cmh.app import create_app

    with TestClient(create_app(), base_url="http://127.0.0.1") as instance:
        yield instance


@pytest.fixture
def live_server(configured_env):
    import uvicorn

    from cmh.app import create_app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
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
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive(), "ASGI server did not stop"
