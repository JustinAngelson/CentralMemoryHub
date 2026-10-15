"""Offline C3 operator tests. Never connect to production or mint real tokens."""
import importlib
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "v2"))

common = importlib.import_module("c3_common")
minting = importlib.import_module("c3_mint")
reports = importlib.import_module("c3_reports")

PASSWORD = "fictional-password-for-unit-test"
TOKEN = "cmh_ak_fictional-token-for-unit-test"
SUBJECT = {"id": str(uuid4()), "slug": "agent-nix-test", "kind": "agent",
           "sponsor_id": str(uuid4()), "status": "active"}
OLD = str(uuid4())
NEW = str(uuid4())


def client_for(existing=(), fail=None, bad_mint=False, personal=False):
    calls = []
    revoked = set()

    def handle(request):
        path = request.url.path
        calls.append((request.method, path))
        if path == fail:
            return httpx.Response(403, json={"secret": TOKEN, "password": PASSWORD})
        if path.endswith("/login"):
            assert json.loads(request.content)["password"] == PASSWORD
            return httpx.Response(200, json={"outcome": "ALLOW"},
                                  headers={"set-cookie": "cmh_session=fake-cookie; Path=/admin"})
        if path.endswith("/whoami"):
            return httpx.Response(200, json={
                "principal": "owner", "role": "owner", "kind": "human",
            })
        if path.endswith("/logout"):
            return httpx.Response(200, json={"outcome": "ALLOW"})
        if path == "/admin/api/credentials" and request.method == "GET":
            return httpx.Response(200, json={"credentials": [
                {**item, "revoked_at": "2026-01-01T00:00:00Z"
                 if item["id"] in revoked else item.get("revoked_at")}
                for item in existing
            ]})
        if path == "/admin/api/credentials":
            payload = json.loads(request.content)
            assert payload == {"principal_id": SUBJECT["id"],
                               "template": "personal-ai-client"
                               if personal else "openclaw-agent-standard",
                               "name": "c3-agent-nix-test"}
            return httpx.Response(201, json={
                "id": NEW, "principal_id": SUBJECT["id"],
                "token": TOKEN.replace("cmh_ak_", "cmh_pk_") if personal else TOKEN,
                "scopes": ["memory.read", "memory.write"] if not bad_mint else None,
            })
        if path.endswith("/revoke"):
            revoked.add(path.split("/")[-2])
            return httpx.Response(200, json={"outcome": "ALLOW"})
        raise AssertionError("Unexpected offline HTTP request")

    return httpx.Client(base_url="https://example.invalid",
                        transport=httpx.MockTransport(handle)), calls, revoked


def credential(**updates):
    return {"id": OLD, "principal_id": SUBJECT["id"], "kind": "api",
            "revoked_at": None, "expires_at": None, **updates}


def test_mint_refuses_active_nonlegacy_before_creating():
    client, calls, _ = client_for([credential()])
    with client, pytest.raises(common.OperatorError):
        minting.mint(client, SUBJECT, "openclaw-agent-standard")
    assert calls == [("GET", "/admin/api/credentials")]


def test_rotate_mints_exactly_one_then_revokes_old_and_verifies():
    client, calls, revoked = client_for([credential()])
    with client:
        made = minting.mint(client, SUBJECT, "openclaw-agent-standard", rotate=True)
    assert made["token"] == TOKEN
    assert revoked == {OLD}
    assert calls.index(("POST", "/admin/api/credentials")) < calls.index(
        ("POST", f"/admin/api/credentials/{OLD}/revoke"))
    assert calls.count(("POST", "/admin/api/credentials")) == 1


def test_owner_uses_personal_template_without_scope_overrides():
    client, calls, _ = client_for(personal=True)
    with client:
        made = minting.mint(client, SUBJECT, "personal-ai-client")
    assert made["token"].startswith("cmh_pk_")
    assert calls.count(("POST", "/admin/api/credentials")) == 1


@pytest.mark.parametrize("old", [
    credential(kind="legacy_shared"),
    credential(revoked_at="2026-01-01T00:00:00Z"),
    credential(expires_at=(datetime.now(UTC) - timedelta(days=1)).isoformat()),
    credential(principal_id=str(uuid4())),
])
def test_legacy_inactive_expired_and_other_principal_do_not_block(old):
    client, _, revoked = client_for([old])
    with client:
        assert minting.mint(client, SUBJECT, "openclaw-agent-standard")["id"] == NEW
    assert not revoked


def test_rotation_failure_cleans_new_credential_without_secret_output(capsys, caplog):
    client, _, revoked = client_for([credential()], fail=f"/admin/api/credentials/{OLD}/revoke")
    with client, pytest.raises(common.OperatorError) as error:
        minting.mint(client, SUBJECT, "openclaw-agent-standard", rotate=True)
    assert NEW in revoked
    output = str(error.value) + capsys.readouterr().out + caplog.text
    assert TOKEN not in output and PASSWORD not in output


def test_invalid_success_payload_is_cleaned_without_revealing_body():
    client, _, revoked = client_for(bad_mint=True)
    with client, pytest.raises(common.OperatorError) as error:
        minting.mint(client, SUBJECT, "openclaw-agent-standard")
    assert NEW in revoked
    assert TOKEN not in str(error.value)


def test_owner_session_hidden_prompts_logout_and_no_output(monkeypatch, capsys, caplog):
    monkeypatch.setattr(common, "OWNER_SLUG", "owner")
    client, calls, _ = client_for()
    prompts = []

    def prompt(label):
        prompts.append(label)
        return PASSWORD if "password" in label.lower() else "owner@example.invalid"

    with client, common.owner_session(client, prompt):
        pass
    assert len(prompts) == 2
    assert calls[-1] == ("POST", "/admin/api/logout")
    assert not client.cookies
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err + caplog.text
    assert "fake-cookie" not in output.out + output.err + caplog.text


def test_failed_logout_revokes_new_before_cookie_cleanup(monkeypatch):
    monkeypatch.setattr(common, "OWNER_SLUG", "owner")
    client, calls, revoked = client_for(fail="/admin/api/logout")
    with (client, pytest.raises(common.OperatorError),
          common.owner_session(client, lambda label: PASSWORD,
                               on_logout_failure=lambda: minting.revoke(client, NEW))):
        assert client.cookies
    assert NEW in revoked
    assert not client.cookies
    assert calls.index(("POST", "/admin/api/logout")) < calls.index(
        ("POST", f"/admin/api/credentials/{NEW}/revoke"))


def test_http_error_is_sanitized():
    client, _, _ = client_for(fail="/admin/api/login")
    with client, pytest.raises(common.OperatorError) as error:
        common.request(client, "POST", "/admin/api/login", json={})
    assert TOKEN not in str(error.value) and PASSWORD not in str(error.value)
    assert "403" in str(error.value)


def test_token_only_printed_once_on_success():
    output = io.StringIO()
    minting.show_credential(SUBJECT["slug"], {
        "id": NEW, "token": TOKEN, "scopes": ["memory.read"],
    }, output)
    printed = output.getvalue()
    assert printed.count(TOKEN) == 1
    assert "copy now" in printed.lower() and "clear" in printed.lower()
    assert PASSWORD not in printed


def test_noninteractive_mint_refused_without_prompt_or_connection(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    monkeypatch.setattr(common, "readonly_connection",
                        lambda: pytest.fail("Must refuse before connecting"))
    assert minting.main(["agent-nix-test"]) == 1
    assert TOKEN not in capsys.readouterr().err


def test_readonly_connection_guards_role_database_and_sql(monkeypatch):
    statements = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            statements.append((query, params))
            return self

    monkeypatch.setenv("CMH_PROD_DATABASE_URL",
                       "postgresql://cmh_app:fictional@db.example.invalid/cmh_v2")
    monkeypatch.setattr(common.psycopg, "connect", lambda **kwargs: Connection())
    with common.readonly_connection():
        pass
    assert statements == [("SET TRANSACTION READ ONLY", None)]
    monkeypatch.setenv("CMH_PROD_DATABASE_URL",
                       "postgresql://cmh_migrate:fictional@db.example.invalid/cmh_v2")
    with pytest.raises(common.OperatorError), common.readonly_connection():
        pytest.fail("Wrong role accepted")


def test_since_requires_timezone():
    assert reports.parse_since("2026-10-15T12:00:00Z").tzinfo is not None
    with pytest.raises(common.OperatorError):
        reports.parse_since("2026-10-15")


def test_slug_lookup_is_parameterized_and_reads_only_approved_fields():
    class Connection:
        def execute(self, sql, params):
            assert "SELECT id,slug,kind,sponsor_id,status FROM principals WHERE slug=%s" in sql
            assert params == (SUBJECT["slug"],)
            return self

        def fetchone(self):
            return SUBJECT

    assert common.lookup(Connection(), SUBJECT["slug"]) == SUBJECT
    with pytest.raises(common.OperatorError):
        common.lookup(Connection(), "invalid';DROP TABLE principals")


def test_reports_select_only_metadata_and_never_write():
    calls = []

    class Result:
        def fetchall(self):
            return []

        def fetchone(self):
            return {"last_seen": None}

    class Connection:
        def execute(self, sql, params=None):
            calls.append(sql)
            return Result()

    conn = Connection()
    assert reports.audit_events(conn, SUBJECT["id"], None) == []
    usage = reports.legacy_usage(conn, [{"id": SUBJECT["id"], "slug": "legacy-mcp"}],
                                 datetime(2026, 10, 15, 15, tzinfo=UTC))
    assert len(usage["hours"]) == 25
    assert all(row["count"] == 0 for row in usage["hours"])
    joined = " ".join(calls).lower()
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in calls)
    for forbidden in ("token_hash", "snapshot", "email", "decision_trace", "request_meta", "content"):
        assert forbidden not in joined
    assert "limit 10" in joined and "mcp.transport" in joined


def test_usage_preserves_nonzero_counts_and_all_time_last_seen():
    seen = datetime(2026, 10, 13, 1, tzinfo=UTC)

    class Connection:
        def execute(self, sql, params):
            self.sql = sql
            assert params[0] == SUBJECT["id"]
            return self

        def fetchall(self):
            return [{"hour": datetime(2026, 10, 15, 14), "count": 7}]

        def fetchone(self):
            assert "max(occurred_at)" in self.sql
            return {"last_seen": seen}

    result = reports.legacy_usage(Connection(), [{"id": SUBJECT["id"], "slug": "legacy-rest"}],
                                  datetime(2026, 10, 15, 15, 20, tzinfo=UTC))
    assert sum(row["count"] for row in result["hours"]) == 7
    assert result["last_seen"] == [{"principal": "legacy-rest", "last_seen": seen}]
