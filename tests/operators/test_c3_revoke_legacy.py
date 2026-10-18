"""Offline legacy retirement contract; no production calls or real credentials."""
import importlib
import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "v2"))
import c3_common as common

NOW = datetime(2026, 10, 18, 15, tzinfo=UTC)
SUBJECT = {"id": str(uuid4()), "slug": "legacy-mcp", "status": "active"}
PASSWORD = "fictional-owner-password"
SECRET = "fictional-secret-must-not-be-printed"


@pytest.fixture
def command():
    return importlib.import_module("c3_revoke_legacy")


def row(**updates):
    return {"id": str(uuid4()), "principal_id": SUBJECT["id"], "kind": "legacy_shared",
            "revoked_at": None, "expires_at": None, **updates}


def harness(monkeypatch, command, rows=(), *, seen=None, confirm="legacy-mcp",
            fail=None, ignore_revoke=False):
    calls, revoked = [], set()

    @contextmanager
    def readonly():
        calls.append("readonly")
        yield object()

    def usage(conn, subjects, now):
        assert subjects == [SUBJECT]
        calls.append("usage")
        return {"last_seen": [{"principal": SUBJECT["slug"],
                              "last_seen": seen or NOW - timedelta(days=2)}]}

    def handle(request):
        path = request.url.path
        calls.append((request.method, path))
        if path == fail:
            raise httpx.ReadTimeout(SECRET, request=request)
        if path.endswith("/login"):
            assert json.loads(request.content)["password"] == PASSWORD
            return httpx.Response(200, json={"outcome": "ALLOW"},
                                  headers={"set-cookie": "cmh_session=fictional-cookie; Path=/admin"})
        if path.endswith("/whoami"):
            return httpx.Response(200, json={"principal": "owner", "role": "owner"})
        if path.endswith("/logout"):
            return httpx.Response(200, json={"outcome": "ALLOW"})
        if path == "/admin/api/credentials":
            return httpx.Response(200, json={"credentials": [
                {**item, "revoked_at": NOW.isoformat() if item["id"] in revoked
                 else item["revoked_at"], "token_hash": SECRET, "name": SECRET}
                for item in rows
            ]})
        if path.endswith("/revoke"):
            if not ignore_revoke:
                revoked.add(path.split("/")[-2])
            return httpx.Response(200, json={"outcome": "ALLOW", "token": SECRET})
        raise AssertionError("Unexpected offline request")

    client = httpx.Client(base_url="https://example.invalid", transport=httpx.MockTransport(handle))
    monkeypatch.setattr(common, "OWNER_SLUG", "owner")
    monkeypatch.setattr(common, "readonly_connection", readonly)
    monkeypatch.setattr(common, "lookup", lambda conn, slug: SUBJECT)
    monkeypatch.setattr(common, "https_client", lambda: client)
    monkeypatch.setattr(command, "legacy_usage", usage)
    monkeypatch.setattr(command, "utcnow", lambda: NOW)
    monkeypatch.setattr("builtins.input", lambda prompt: confirm)
    original_session = common.owner_session
    monkeypatch.setattr(common, "owner_session",
                        lambda client: original_session(client, lambda label: PASSWORD))
    return calls, revoked, client


@pytest.mark.parametrize("slug", ["owner", "agent-nix-test", "legacy", "../legacy-mcp"])
def test_nonlegacy_slug_refused_before_sql_or_login(command, monkeypatch, slug):
    monkeypatch.setattr(common, "readonly_connection", lambda: pytest.fail("Unexpected SQL"))
    monkeypatch.setattr(common, "https_client", lambda: pytest.fail("Unexpected HTTPS"))
    assert command.main([slug]) == 1


@pytest.mark.parametrize("age", [timedelta(hours=23, minutes=59), timedelta(seconds=-1)])
def test_recent_or_future_last_seen_refuses_before_confirmation_and_login(
    command, monkeypatch, age,
):
    calls, _, _ = harness(monkeypatch, command, seen=NOW - age)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("Unexpected confirmation"))
    assert command.main(["legacy-mcp"]) == 1
    assert calls == ["readonly", "usage"]


def test_wrong_confirmation_refuses_before_login(command, monkeypatch):
    calls, _, _ = harness(monkeypatch, command, confirm="legacy-rest")
    assert command.main(["legacy-mcp"]) == 1
    assert calls == ["readonly", "usage"]


@pytest.mark.parametrize("slug", ["legacy-mcp", "legacy-rest"])
def test_only_selected_principal_active_legacy_credentials_revoked(
    command, monkeypatch, capsys, slug,
):
    subject = {**SUBJECT, "slug": slug}
    monkeypatch.setitem(SUBJECT, "slug", slug)
    wanted = [row(), row()]
    ignored = [row(principal_id=str(uuid4())), row(kind="api"),
               row(kind="personal_ai_client"), row(revoked_at=NOW.isoformat()),
               row(expires_at=(NOW - timedelta(seconds=1)).isoformat())]
    calls, revoked, client = harness(
        monkeypatch, command, [*wanted, *ignored], seen=NOW - timedelta(hours=24), confirm=slug,
    )
    assert subject["slug"] == slug
    assert command.main([slug]) == 0
    assert revoked == {item["id"] for item in wanted}
    assert calls[:2] == ["readonly", "usage"]
    assert calls.count(("GET", "/admin/api/credentials")) == 2
    assert calls[-1] == ("POST", "/admin/api/logout")
    assert not client.cookies
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["principal_slug"] == slug
    assert report["active_legacy_credentials_after"] == 0
    assert {item["credential_id_prefix"] for item in report["revoked"]} == {
        item["id"][:8] for item in wanted
    }
    assert all(item["revoked_at"] == NOW.isoformat() for item in report["revoked"])
    assert all(item["id"] not in output for item in wanted)
    assert SECRET not in output and PASSWORD not in output


@pytest.mark.parametrize("missing", [False, True])
def test_unverified_revocation_is_failure_and_logs_out(command, monkeypatch, missing):
    wanted = row()
    calls, _, _ = harness(monkeypatch, command, [wanted], ignore_revoke=True)
    if missing:
        # A disappeared credential is not proof of an observed revoked_at.
        original = common.request
        listed = 0

        def request(client, method, path, **kwargs):
            nonlocal listed
            result = original(client, method, path, **kwargs)
            if method == "GET" and path == "/admin/api/credentials":
                listed += 1
                if listed == 2:
                    return {"credentials": []}
            return result

        monkeypatch.setattr(common, "request", request)
    assert command.main(["legacy-mcp"]) == 1
    assert calls[-1] == ("POST", "/admin/api/logout")


def test_unknown_http_outcome_never_retried_and_no_secret_output(
    command, monkeypatch, capsys, caplog,
):
    wanted = row()
    path = f"/admin/api/credentials/{wanted['id']}/revoke"
    calls, _, client = harness(monkeypatch, command, [wanted], fail=path)
    assert command.main(["legacy-mcp"]) == 1
    assert calls.count(("POST", path)) == 1
    assert calls[-1] == ("POST", "/admin/api/logout")
    assert not client.cookies
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err + caplog.text
    assert PASSWORD not in output.out + output.err + caplog.text
    assert "fictional-cookie" not in output.out + output.err + caplog.text


def test_no_override_flag(command, monkeypatch):
    monkeypatch.setattr(common, "readonly_connection", lambda: pytest.fail("Unexpected SQL"))
    with pytest.raises(SystemExit) as error:
        command.main(["legacy-mcp", "--force"])
    assert error.value.code == 2
