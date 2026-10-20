"""Offline namespace operator contract; no production calls or real credentials."""
import importlib
import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "v2"))
import c3_common as common

NOW = datetime(2026, 10, 20, 20, tzinfo=UTC)
EMAIL = "owner@example.invalid"
PASSWORD = "fictional-owner-password"
SECRET = "fictional-response-value-must-not-be-printed"
DEFAULT = object()


@pytest.fixture
def command():
    return importlib.import_module("ns_create")


def namespace(path="org.rollups", **updates):
    return {"id": uuid4(), "path": path, "mode": "flag", "governed": False,
            "created_at": NOW, **updates}


def harness(monkeypatch, *, target="org.rollups", existing=None, parent_exists=True,
            post_row=DEFAULT, fail=None, role="owner"):
    calls = []
    created = namespace(target) if post_row is DEFAULT else post_row
    reads = 0

    class Connection:
        def execute(self, sql, params):
            assert sql.lstrip().upper().startswith("SELECT")
            assert "*" not in sql
            for forbidden in ("email", "password", "token", "hash", "description"):
                assert forbidden not in sql.lower()
            assert len(params) == 1
            self.path = params[0]
            calls.append(("SELECT", self.path))
            return self

        def fetchone(self):
            if self.path == target:
                return existing if reads == 1 else created
            assert self.path == target.rsplit(".", 1)[0]
            return namespace(self.path) if parent_exists else None

    @contextmanager
    def readonly():
        nonlocal reads
        reads += 1
        calls.append("readonly")
        yield Connection()

    def handle(request):
        path = request.url.path
        calls.append((request.method, path))
        if path == "/admin/api/login":
            assert json.loads(request.content) == {"email": EMAIL, "password": PASSWORD}
            return httpx.Response(200, json={"outcome": "ALLOW"}, headers={
                "set-cookie": "cmh_session=fictional-cookie; Path=/admin",
            })
        if path == "/admin/api/whoami":
            return httpx.Response(200, json={"principal": "owner", "role": role})
        if path == "/admin/api/logout":
            return httpx.Response(200, json={"outcome": "ALLOW"})
        if path == "/admin/api/namespaces":
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "path": target, "description": "Rollup summaries", "mode": "flag",
            }
            if fail == "raise":
                raise httpx.ReadTimeout(SECRET, request=request)
            if fail == "deny":
                return httpx.Response(200, json={"outcome": "DENY", "detail": SECRET})
            if fail == "http":
                return httpx.Response(403, json={"detail": SECRET})
            return httpx.Response(201, json={"namespace": {"id": str(uuid4())},
                                            "untrusted_extra": SECRET})
        raise AssertionError("Unexpected offline request")

    client = httpx.Client(base_url="https://example.invalid", transport=httpx.MockTransport(handle))
    monkeypatch.setattr(common, "OWNER_SLUG", "owner")
    monkeypatch.setattr(common, "readonly_connection", readonly)
    monkeypatch.setattr(common, "https_client", lambda: client)
    original_session = common.owner_session
    monkeypatch.setattr(common, "owner_session", lambda client: original_session(
        client, lambda label: PASSWORD if "password" in label.lower() else EMAIL,
    ))
    return calls, client, created


@pytest.mark.parametrize("path", [
    "org.finance", "org.finance.x", "people.justin.private", "agents.nix-angelson.private",
    "inbox.x", "system.x", "Org.Rollups", "org.a.b.c", "org.rollups/x",
    "org.clients.Finance", "org.clients.example.extra", "org.-bad", "org._bad",
    "org." + "a" * 64, "org.clients." + "a" * 64, "org.rollups\n", "org.clients.",
])
def test_refused_paths_never_connect(command, monkeypatch, path):
    monkeypatch.setattr(common, "readonly_connection", lambda: pytest.fail("Unexpected SQL"))
    monkeypatch.setattr(common, "https_client", lambda: pytest.fail("Unexpected HTTPS"))
    assert command.main([path, "--description", "Rollup summaries"]) == 1


@pytest.mark.parametrize("description", [
    "", " ", "a" * 201, "one\ntwo", "one\rtwo", "one\n", "one\u2028two",
])
def test_invalid_descriptions_never_connect(command, monkeypatch, description):
    monkeypatch.setattr(common, "readonly_connection", lambda: pytest.fail("Unexpected SQL"))
    monkeypatch.setattr(common, "https_client", lambda: pytest.fail("Unexpected HTTPS"))
    assert command.main(["org.rollups", "--description", description]) == 1


@pytest.mark.parametrize("mode", ["flag", "queue"])
def test_existing_target_exits_without_login(command, monkeypatch, capsys, mode):
    existing = namespace(mode=mode, governed=mode == "queue")
    calls, _, _ = harness(monkeypatch, existing=existing)
    assert command.main(["org.rollups", "--description", "Rollup summaries"]) == 0
    assert calls == ["readonly", ("SELECT", "org.rollups")]
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "already exists" and report["mode"] == mode
    assert report["namespace_id_prefix"] == str(existing["id"])[:8]


def test_missing_parent_refuses_without_login(command, monkeypatch):
    calls, _, _ = harness(monkeypatch, parent_exists=False)
    assert command.main(["org.rollups", "--description", "Rollup summaries"]) == 1
    assert calls == ["readonly", ("SELECT", "org.rollups"), ("SELECT", "org")]


@pytest.mark.parametrize("path", ["org.rollups", "org.clients.example-mechanical"])
def test_one_native_post_logout_and_verified_metadata(
    command, monkeypatch, capsys, caplog, path,
):
    calls, client, created = harness(monkeypatch, target=path)
    assert command.main([path, "--description", "Rollup summaries"]) == 0
    assert calls.count(("POST", "/admin/api/namespaces")) == 1
    assert calls.count(("POST", "/admin/api/login")) == 1
    assert calls.count(("POST", "/admin/api/logout")) == 1
    assert calls.index(("SELECT", path.rsplit(".", 1)[0])) < calls.index(
        ("POST", "/admin/api/login"))
    assert calls[-3:] == [("POST", "/admin/api/logout"), "readonly", ("SELECT", path)]
    assert not client.cookies
    output = capsys.readouterr()
    assert not output.err
    assert json.loads(output.out) == {
        "path": path, "mode": "flag", "governed": False,
        "namespace_id_prefix": str(created["id"])[:8], "created_at": NOW.isoformat(),
    }
    for sensitive in (EMAIL, PASSWORD, SECRET, "fictional-cookie", str(created["id"])):
        assert sensitive not in output.out + output.err + caplog.text


@pytest.mark.parametrize("failure", ["raise", "deny", "http"])
def test_post_failure_never_retries_and_logs_out(
    command, monkeypatch, capsys, caplog, failure,
):
    calls, client, _ = harness(monkeypatch, fail=failure)
    assert command.main(["org.rollups", "--description", "Rollup summaries"]) == 1
    assert calls.count(("POST", "/admin/api/namespaces")) == 1
    assert calls[-1] == ("POST", "/admin/api/logout")
    assert calls.count("readonly") == 1
    assert not client.cookies
    output = capsys.readouterr()
    assert not output.out
    assert set(json.loads(output.err)) == {"error"}
    for sensitive in (EMAIL, PASSWORD, SECRET, "fictional-cookie"):
        assert sensitive not in output.out + output.err + caplog.text


@pytest.mark.parametrize("post_row", [
    None, namespace(mode="queue"), namespace(governed=True), namespace(path="org.other"),
])
def test_post_check_must_verify_flag_and_ungoverned(
    command, monkeypatch, capsys, post_row,
):
    calls, _, _ = harness(monkeypatch, post_row=post_row)
    assert command.main(["org.rollups", "--description", "Rollup summaries"]) == 1
    assert calls.count(("POST", "/admin/api/namespaces")) == 1
    assert json.loads(capsys.readouterr().err) == {
        "error": "Namespace creation could not be verified.",
    }


def test_nonowner_login_refused_and_logged_out(command, monkeypatch):
    calls, client, _ = harness(monkeypatch, role="partner")
    assert command.main(["org.rollups", "--description", "Rollup summaries"]) == 1
    assert ("POST", "/admin/api/namespaces") not in calls
    assert calls[-1] == ("POST", "/admin/api/logout")
    assert not client.cookies


def test_no_mode_override(command, monkeypatch, capsys):
    monkeypatch.setattr(common, "readonly_connection", lambda: pytest.fail("Unexpected SQL"))
    monkeypatch.setattr(common, "https_client", lambda: pytest.fail("Unexpected HTTPS"))
    with pytest.raises(SystemExit) as error:
        command.main(["org.rollups", "--description", "Rollup summaries", "--mode", "queue"])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err) == {"error": "Invalid namespace arguments."}


def test_missing_description_is_json_error_before_connection(command, monkeypatch, capsys):
    monkeypatch.setattr(common, "readonly_connection", lambda: pytest.fail("Unexpected SQL"))
    monkeypatch.setattr(common, "https_client", lambda: pytest.fail("Unexpected HTTPS"))
    with pytest.raises(SystemExit) as error:
        command.main(["org.rollups"])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert json.loads(output.err) == {"error": "Invalid namespace arguments."}


def test_rollups_seed_entry_after_ops():
    entries = json.loads((Path(__file__).resolve().parents[2] / "seed/namespaces.yaml").read_text())
    position = next(index for index, row in enumerate(entries) if row["path"] == "org.ops")
    assert entries[position + 1] == {"path": "org.rollups", "mode": "flag", "governed": False}
    assert sum(row["path"] == "org.rollups" for row in entries) == 1
