"""Identity contract harness; application requests use committed transactions.

Independent DENY/QUEUE transactions and concurrent audit-only requests persist.
No teardown truncates/deletes audit rows. All actor fixtures are role-based.
"""

import hashlib
import json
import os
import secrets
import socket
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import SensitiveTestValue
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import create_engine, event, text


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class Clock:
    def __init__(self):
        self.now = datetime.now(UTC)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class IdentityCase:
    def __repr__(self):
        return "<identity contract harness; credentials redacted>"

    def __init__(self, engine, admin, bootstrap, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        import cmh.app

        self.engine = engine
        self.engine.real = engine
        self.engine.connection = None
        self.admin = admin
        self.clock = Clock()
        self.origin = "https://configuration.example"
        self.bootstrap = bootstrap
        self.password = SensitiveTestValue(secrets.token_urlsafe(24))
        self.clients = []
        self.server = None
        self.server_thread = None
        self.socket_path = str(tmp_path / "identity.sock")
        self.socket = None
        monkeypatch.setenv("CMH_PUBLIC_URL", self.origin)
        monkeypatch.setattr(cmh.app, "build_engine", lambda *a, **kw: self.engine)
        self.app = cmh.app.create_app()
        self.app.state.clock = self.clock
        self.owner_client = TestClient(self.app, base_url=self.origin)
        self.owner_client.__enter__()
        self.clients.append(self.owner_client)
        self.owner = self.setup_owner()
        self.partner_a, self.client_a = self.human("partner-a")
        self.partner_b, self.client_b = self.human("partner-b")
        self.agent_a = self.agent(self.client_a, self.partner_a, "agent-a1")
        self.agent_b = self.agent(self.client_b, self.partner_b, "agent-b1")
        self.owner_token = self.credential(self.owner_client, self.owner, "personal-ai-client")
        self.readonly_token = self.credential(
            self.owner_client, self.owner, "personal-ai-client-readonly"
        )
        self.transaction = None
        self.namespace = "org.clients.test-" + secrets.token_hex(8)
        require(self.request(self.owner_client, "POST", "/admin/api/namespaces", json={
            "path": self.namespace,
        }).status_code == 201, "Per-test namespace setup failed")

    def request(self, client, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            headers.setdefault("Origin", self.origin)
        return client.request(method, path, headers=headers, **kwargs)

    def setup_owner(self):
        with self.admin.connect() as connection:
            exists = connection.execute(text("SELECT to_regclass('public.principals')")).scalar()
            require(exists is not None, "Phase 1 migration 0002_identity is missing")
            owner = connection.execute(text(
                "SELECT id, slug FROM principals WHERE role='owner'"
            )).mappings().first()
        if owner is None:
            response = self.request(self.owner_client, "POST", "/admin/api/bootstrap", headers={
                "Authorization": "Bearer " + self.bootstrap,
            }, json={
                "slug": "owner", "display_name": "owner",
                "email": "owner@example.invalid", "password": self.password,
            })
            require(response.status_code == 201, "Owner bootstrap setup failed")
            self.admin._test_owner_password = self.password
            return response.json()["principal"]
        # A run's bootstrap scenario is ordered first and stores the synthetic
        # owner's password privately on the session fixture, never in evidence.
        self.password = self.admin._test_owner_password
        response = self.request(self.owner_client, "POST", "/admin/api/login", json={
            "email": "owner@example.invalid", "password": self.password,
        })
        require(response.status_code == 200, "Owner login setup failed")
        return dict(owner)

    def human(self, slug):
        from fastapi.testclient import TestClient

        unique = slug + "-" + secrets.token_hex(4)
        password = SensitiveTestValue(secrets.token_urlsafe(24))
        response = self.request(self.owner_client, "POST", "/admin/api/principals", json={
            "kind": "human", "slug": unique, "display_name": slug.replace("-", "_"),
            "role": "partner", "tier": 3, "email": unique + "@example.invalid",
            "password": password,
        })
        require(response.status_code == 201, "Partner setup failed")
        principal = response.json()["principal"]
        response = self.request(self.owner_client, "POST", "/admin/api/grants", json={
            "principal_id": str(principal["id"]), "namespace": "org", "permission": "write",
        })
        require(response.status_code == 201, "Partner namespace setup failed")
        client = TestClient(self.app, base_url=self.origin)
        self.clients.append(client)
        response = self.request(client, "POST", "/admin/api/login", json={
            "email": unique + "@example.invalid", "password": password,
        })
        require(response.status_code == 200, "Partner login setup failed")
        return principal, client

    def agent(self, client, sponsor, slug):
        response = self.request(client, "POST", "/admin/api/principals", json={
            "kind": "agent", "slug": slug + "-" + secrets.token_hex(4),
            "display_name": slug.replace("-", "_"), "tier": 2,
            "sponsor_id": str(sponsor["id"]), "template": "openclaw-agent-standard",
            "credential_name": slug + "-runtime",
        })
        require(response.status_code == 201, "Agent template setup failed")
        data = response.json()
        data["credential"]["token"] = SensitiveTestValue(data["credential"]["token"])
        return data

    def credential(self, client, principal, template, **extra):
        response = self.request(client, "POST", "/admin/api/credentials", json={
            "principal_id": str(principal["id"]), "template": template,
            "name": "test-client-" + secrets.token_hex(4), **extra,
        })
        require(response.status_code == 201, "Credential setup failed")
        result = response.json()
        result["token"] = SensitiveTestValue(result["token"])
        return result

    def bearer(self, credential, method="GET", path="/api/whoami", **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = "Bearer " + credential["token"]
        return self.owner_client.request(method, path, headers=headers, **kwargs)

    def check(self, credential, operation="memory.write", namespace="org", **extra):
        return self.bearer(credential, "POST", "/api/access/check", json={
            "operation": operation, "namespace": namespace, **extra,
        })

    def sql(self, statement, **params):
        with self.engine.connect() as connection:
            return connection.execute(text(statement), params).mappings().all()

    def tamper(self, statement, **params):
        # Administrative simulations commit; tests restore global mutations
        # explicitly. Audit rows are never removed in ordinary teardown.
        if self.engine.connection is None:
            with self.admin.begin() as connection:
                connection.execute(text(statement), params)
        else:
            connection = self.engine.connection
            connection.execute(text("SET LOCAL ROLE postgres"))
            try:
                connection.execute(text(statement), params)
            finally:
                connection.execute(text("SET LOCAL ROLE cmh_app"))

    def start_body(self, concurrent=False):
        # Each app/SDK server has fresh in-process rate-limit state; no request
        # borrows an outer test transaction. Principals and namespaces are unique.
        pass

    def close(self):
        if self.server:
            self.server.should_exit = True
            self.server_thread.join(timeout=10)
            require(not self.server_thread.is_alive(), "Unix MCP server failed to stop")
            self.socket.close()
        for client in self.clients:
            client.close()
        self.owner_client.__exit__(None, None, None)
        if self.transaction is not None:
            if self.transaction.is_active:
                self.transaction.rollback()
            self.engine.connection.close()
            self.engine.connection = None

    def start_mcp(self):
        if self.server:
            return
        import uvicorn

        from cmh.app import create_app

        app = create_app()
        app.state.clock = self.clock
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.bind(self.socket_path)
        self.server = uvicorn.Server(uvicorn.Config(
            app, log_config=None, access_log=False, lifespan="on"
        ))
        self.server_thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True
        )
        self.server_thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        require(self.server.started, "Unix MCP server failed to start")
        from conftest import assert_v1_ports_only

        assert_v1_ports_only()

    @asynccontextmanager
    async def mcp(self, credential):
        self.start_mcp()
        async with (
            httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(uds=self.socket_path),
                headers={"Authorization": "Bearer " + credential["token"]},
            ) as http,
            streamable_http_client(
                "http://configuration.example/mcp", http_client=http
            ) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session

    async def tool(self, credential, name, arguments):
        async with self.mcp(credential) as session:
            result = await session.call_tool(name, arguments)
            return result, json.loads(result.content[0].text)

    def audit(self):
        with self.admin.connect() as connection:
            return connection.execute(text(
                "SELECT * FROM audit_events ORDER BY seq"
            )).mappings().all()

    def body_audit(self):
        with self.engine.connect() as connection:
            return connection.execute(text(
                "SELECT * FROM audit_events ORDER BY seq"
            )).mappings().all()


@pytest.fixture
def identity(configured_env, audit_admin, monkeypatch, tmp_path, request):
    from cmh.db.engine import normalize_database_url
    from cmh.seed import seed_database

    seed_database(audit_admin)
    engine = create_engine(
        normalize_database_url(os.environ["CMH_TEST_DATABASE_URL"]), hide_parameters=True
    )

    @event.listens_for(engine, "connect")
    def app_role(dbapi_connection, _record):
        with dbapi_connection.cursor() as cursor:
            cursor.execute("SET ROLE cmh_app")
        dbapi_connection.commit()

    case = IdentityCase(engine, audit_admin, configured_env, monkeypatch, tmp_path)
    case.start_body(concurrent=request.node.get_closest_marker("concurrent_audit") is not None)
    try:
        yield case
    finally:
        case.close()
        engine.dispose()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()
