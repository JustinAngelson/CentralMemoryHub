import json
import logging
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALID = {"first_name": " owner ", "email": " Owner@Example.com "}


def post(client, body=None, ip="192.0.2.1", **kwargs):
    return client.post(
        "/api/waitlist", json=VALID if body is None else body,
        environ_base={"REMOTE_ADDR": ip}, **kwargs,
    )


def test_deployment_headers(client, monkeypatch):
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    response = client.get("/landing")
    assert "frame-ancestors 'none';" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "'unsafe-inline'" in response.headers["Content-Security-Policy"]


def test_development_headers(client):
    response = client.get("/landing")
    csp = response.headers["Content-Security-Policy"]
    assert "frame-ancestors https://replit.com https://*.replit.com;" in csp
    assert "X-Frame-Options" not in response.headers


@pytest.mark.parametrize("body", [
    [], {}, {"first_name": 1, "email": "owner@example.com"},
    {"first_name": "", "email": "owner@example.com"},
    {"first_name": " " * 4, "email": "owner@example.com"},
    {"first_name": "x" * 101, "email": "owner@example.com"},
    {"first_name": "owner\n", "email": "owner@example.com"},
    {"first_name": "own\x00er", "email": "owner@example.com"},
    {"first_name": "\ud800", "email": "owner@example.com"},
    {"first_name": "owner", "email": 1},
    {"first_name": "owner", "email": ""},
    {"first_name": "owner", "email": "not-an-email"},
    {"first_name": "owner", "email": "a..b@example.com"},
    {"first_name": "owner", "email": "owner@-example.com"},
    {"first_name": "owner", "email": "a" * 64 + "@" + "b" * 44 + ".example.com"},
])
def test_validation(client, runtime, body):
    assert post(client, body).status_code == 400
    assert runtime[3].Waitlist.query.count() == 0


@pytest.mark.parametrize("data,content_type", [
    ('{"first_name":', "application/json"),
    ("null", "application/json"),
    ("", "application/json"),
    ("first_name=owner&email=owner@example.com", "application/x-www-form-urlencoded"),
    ("{}", "text/plain"),
    ("x" * 2049, "application/json"),
])
def test_body_validation(client, runtime, data, content_type):
    response = client.post("/api/waitlist", data=data, content_type=content_type)
    assert response.status_code == 400
    assert runtime[3].Waitlist.query.count() == 0


def test_valid_casefold_and_duplicate(client, runtime):
    assert post(client).json == {"ok": True}
    entry = runtime[3].Waitlist.query.one()
    assert (entry.first_name, entry.email) == ("owner", "owner@example.com")
    assert post(client, {"first_name": "partner_a", "email": "OWNER@EXAMPLE.COM"}).json == {"ok": True}
    assert runtime[3].Waitlist.query.count() == 1


def test_email_120_character_boundary(client, runtime):
    email = "a" * 64 + "@" + "b" * 43 + ".example.com"
    assert len(email) == 120
    assert post(client, {"first_name": "owner", "email": email}).status_code == 200
    assert runtime[3].Waitlist.query.one().email == email


def test_per_ip_hour_limit_and_spoofed_header(client, runtime):
    for _ in range(5):
        assert post(client).status_code == 200
    assert post(client, headers={"X-Forwarded-For": "203.0.113.99"}).status_code == 429
    assert post(client, ip="192.0.2.2").status_code == 200
    assert runtime[3].Waitlist.query.count() == 1


def test_per_ip_rolling_window(runtime):
    routes = runtime[2]
    limiter = routes.RateLimiter()
    assert not limiter.is_rate_limited("waitlist:test", 1, window_seconds=3600)
    assert limiter.is_rate_limited("waitlist:test", 1, window_seconds=3600)
    limiter.request_counts["waitlist:test"] = {datetime.now() - timedelta(hours=2): 1}
    assert not limiter.is_rate_limited("waitlist:test", 1, window_seconds=3600)


def seed(runtime, count, hours=0):
    _, db, _, models = runtime
    db.session.add_all([
        models.Waitlist(first_name="owner", email=f"owner{i}@example.com",
                        created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours))
        for i in range(count)
    ])
    db.session.commit()


def test_persistent_rolling_cap_and_duplicate_at_capacity(client, runtime, monkeypatch):
    import urllib.request
    calls = []
    monkeypatch.setenv("WAITLIST_WEBHOOK_URL", "https://webhook.example.test")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: calls.append(a))
    seed(runtime, 200)
    # Simulate another worker/restart: the database, not limiter memory, is authoritative.
    runtime[2].rate_limiter.request_counts.clear()
    assert post(client, ip="192.0.2.3").status_code == 429
    assert runtime[3].Waitlist.query.count() == 200
    assert calls == []
    assert post(client, {"first_name": "owner", "email": "OWNER0@EXAMPLE.COM"}).json == {"ok": True}
    assert runtime[3].Waitlist.query.count() == 200


def test_cap_counts_only_last_24_hours(client, runtime):
    seed(runtime, 200, hours=25)
    assert post(client).status_code == 200
    assert runtime[3].Waitlist.query.count() == 201


def test_webhook_only_for_new_rows_and_no_pii_logs(client, runtime, monkeypatch, caplog):
    import threading
    import urllib.request
    calls = []

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    def fail(request, timeout):
        calls.append((json.loads(request.data), timeout))
        raise RuntimeError("owner@example.com owner private detail")

    monkeypatch.setenv("WAITLIST_WEBHOOK_URL", "https://webhook.example.test")
    monkeypatch.setattr(threading, "Thread", ImmediateThread)
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with caplog.at_level(logging.WARNING):
        assert post(client).status_code == 200
        assert post(client, {"first_name": "partner_a", "email": "OWNER@EXAMPLE.COM"}).status_code == 200
    assert calls == [({"first_name": "owner", "email": "owner@example.com",
                      "source": "CentralMemoryHub.com"}, 5)]
    assert "RuntimeError" in caplog.text
    assert "owner@example.com" not in caplog.text
    assert "private detail" not in caplog.text


def test_database_error_logs_no_parameters(client, runtime, monkeypatch, caplog):
    def fail():
        raise RuntimeError("owner@example.com partner_a private detail")
    monkeypatch.setattr(runtime[1].session, "commit", fail)
    with caplog.at_level(logging.ERROR):
        assert post(client).status_code == 500
    assert "RuntimeError" in caplog.text
    assert "owner@example.com" not in caplog.text
    assert "partner_a" not in caplog.text


@pytest.mark.parametrize("public_url,expected", [
    ("https://cmh.example.com/", "https://cmh.example.com"),
    (None, "https://requested.example.com"),
])
def test_dynamic_openapi(client, monkeypatch, public_url, expected):
    monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
    if public_url:
        monkeypatch.setenv("CMH_PUBLIC_URL", public_url)
    response = client.get("/openapi.json", base_url="https://requested.example.com")
    assert response.json["servers"][0]["url"] == expected
    assert "your-instance" not in json.dumps(response.json["servers"])
    placeholder = json.loads((ROOT / "openapi-schema-fixed.json").read_text())["servers"][0]["url"]
    assert response.json["servers"][0]["url"] != placeholder


def test_trusted_hops_are_explicit(runtime, monkeypatch):
    import app
    assert app.trusted_proxy_hops() == 0
    monkeypatch.setenv("CMH_TRUSTED_PROXY_HOPS", "2")
    assert app.trusted_proxy_hops() == 2
    monkeypatch.setenv("CMH_TRUSTED_PROXY_HOPS", "-1")
    with pytest.raises(ValueError):
        app.trusted_proxy_hops()


def test_verified_hops_ignore_client_supplied_prefix(runtime, monkeypatch):
    from flask import Flask, request
    from werkzeug.middleware.proxy_fix import ProxyFix

    import app
    monkeypatch.setenv("CMH_TRUSTED_PROXY_HOPS", "2")
    probe = Flask("test-only-proxy-probe")
    probe.wsgi_app = ProxyFix(probe.wsgi_app, x_for=app.trusted_proxy_hops())
    probe.add_url_rule("/ip", view_func=lambda: request.remote_addr)
    response = probe.test_client().get(
        "/ip", headers={"X-Forwarded-For": "203.0.113.99, 192.0.2.1, 192.0.2.2"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert response.text == "192.0.2.1"


def test_postgres_advisory_guard(runtime, client, monkeypatch):
    db = runtime[1]
    statements = []
    original = db.session.execute

    def execute(statement, *args, **kwargs):
        if "pg_advisory_xact_lock" in str(statement):
            statements.append(str(statement))
            return None
        return original(statement, *args, **kwargs)

    monkeypatch.setattr(db.engine.dialect, "name", "postgresql")
    monkeypatch.setattr(db.session, "execute", execute)
    assert post(client).status_code == 200
    assert len(statements) == 1


def test_stored_message_rendered_only_as_escaped_html(runtime):
    _, db, _, models = runtime
    attack = "<img src=x onerror=alert(1)>"
    db.session.add(models.GPTMessage(sender_agent=attack, receiver_agent=attack,
                                    message_type=attack, content=attack))
    db.session.commit()
    stored = models.GPTMessage.query.one().to_dict()
    template = (ROOT / "templates/agent_view.html").read_text()
    match = re.search(r"modalBody\.innerHTML = (msgs\.map\(m => `.*?`\)\.join\(''\)|renderSessionMessages\(msgs\));", template, re.DOTALL)
    # Find the exact current renderer, including the vulnerable pre-hotfix version.
    if match is None:
        match = re.search(r"modalBody\.innerHTML = (msgs\.map\(m => `.*?`\)\.join\(''\));", template, re.DOTALL)
    assert match, "Session messages must use the tested renderer"
    helper = ROOT / "static/js/security.js"
    code = (helper.read_text() if helper.exists() else "") + """
const msgs = JSON.parse(process.argv[1]);
const badgeClass = {instruction: 'bg-primary', status_update: 'bg-secondary'};
process.stdout.write(""" + match.group(1) + ");"
    fragment = subprocess.run(["node", "-e", code, json.dumps([stored])],
                              check=True, capture_output=True, text=True).stdout
    assert attack not in fragment
    assert fragment.count("&lt;img src=x onerror=alert(1)&gt;") == 4


def test_templates_load_shared_escape_helper():
    for name in ("agent_view.html", "api_keys.html"):
        text = (ROOT / "templates" / name).read_text()
        assert "js/security.js" in text
        assert "onclick=\"confirmRevoke('${" not in text
        assert "onclick=\"handleViewAgent('${" not in text


def test_no_server_data_in_inline_event_handlers(runtime):
    for path in (ROOT / "templates").rglob("*.html"):
        source = path.read_text()
        runtime[0].jinja_env.parse(source)
        assert not re.search(r'\bon[a-z]+=["\'][^>]*\{\{', source), path
        assert "|safe" not in source
        assert "insertAdjacentHTML" not in source


def test_actual_js_renderers_and_inline_script_syntax():
    # Run real template renderers, not hand-coded copies. A minimal DOM stores
    # generated fragments; it does not substitute for a signed-in browser test.
    result = subprocess.run(["node", str(ROOT / "tests/v1/renderers.cjs")],
                            check=True, capture_output=True, text=True)
    assert "safe renderers and 400/429 UI: PASS" in result.stdout
