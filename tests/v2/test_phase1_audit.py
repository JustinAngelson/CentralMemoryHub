"""Audit gate §4: independent canonical oracle and real concurrent writers."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from test_phase1_credentials import denied


def canonical(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value).lower()
    raise TypeError("Unexpected audit serialization type")


def oracle(rows):
    previous = "0" * 64
    for row in rows:
        assert row["prev_hash"] == previous
        event = {key: value for key, value in row.items() if key not in {"hash", "prev_hash"}}
        encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             default=canonical).encode("utf-8")
        expected = hashlib.sha256(previous.encode("ascii") + encoded).hexdigest()
        assert row["hash"] == expected
        previous = expected


@pytest.mark.concurrent_audit
def test_4_2_thousand_mixed_events_verify_with_earlier_events(identity):
    credential = identity.owner_token
    identity.tamper("UPDATE credentials SET rate_limit=5000 WHERE id=:id", id=credential["id"])
    baseline = len(identity.body_audit())
    for index in range(1000):
        operation = "memory.read" if index % 2 == 0 else "policy.write"
        response = identity.check(credential, operation)
        assert response.status_code == (200 if index % 2 == 0 else 403)
    rows = identity.body_audit()
    assert len(rows) >= baseline + 1000
    assert {"ALLOW", "DENY"} <= {row["outcome"] for row in rows[baseline:]}
    oracle(rows)
    response = identity.bearer(credential, path="/api/audit/verify")
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_4_3_tamper_detected_at_exact_sequence(identity):
    for _ in range(3):
        assert identity.check(identity.owner_token, "memory.read").status_code == 200
    rows = identity.body_audit()
    target = rows[len(rows) // 2]["seq"]
    identity.tamper("UPDATE audit_events SET actor='tampered-test-actor' WHERE seq=:seq", seq=target)
    result = identity.bearer(identity.owner_token, path="/api/audit/verify")
    assert result.status_code == 200
    assert result.json()["valid"] is False
    assert result.json()["bad_seq"] == target


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_4_4_app_role_cannot_mutate_audit(identity, operation):
    assert identity.check(identity.owner_token, "memory.read").status_code == 200
    before = len(identity.body_audit())
    with identity.engine.begin() as connection:
        assert connection.execute(text("SELECT current_user")).scalar_one() == "cmh_app"
        with pytest.raises(ProgrammingError) as error, connection.begin_nested():
            statements = {
                "UPDATE": "UPDATE audit_events SET actor='forbidden'",
                "DELETE": "DELETE FROM audit_events",
                "TRUNCATE": "TRUNCATE audit_events",
            }
            connection.execute(text(statements[operation]))
        assert error.value.orig.sqlstate == "42501"
    assert len(identity.body_audit()) == before


@pytest.mark.concurrent_audit
def test_4_6_ten_concurrent_real_committed_audited_operations(identity):
    before = len(identity.audit())

    def operate(index):
        # Separate clients and physical DB sessions; no shared outer transaction
        # or test-side serialization can make the database chain pass.
        from fastapi.testclient import TestClient

        client = TestClient(identity.app, base_url=identity.origin)
        try:
            return client.post("/api/access/check", headers={
                "Authorization": "Bearer " + identity.owner_token["token"],
            }, json={"operation": "memory.read" if index % 2 == 0 else "policy.write",
                     "namespace": "org"}).status_code
        finally:
            client.close()

    with ThreadPoolExecutor(max_workers=10) as workers:
        responses = list(workers.map(operate, range(10)))
    assert responses.count(200) == 5
    assert responses.count(403) == 5
    rows = identity.audit()
    assert len(rows) >= before + 10
    assert len({row["request_meta"]["request_id"] for row in rows[before:]}) == 10
    oracle(rows)
    response = identity.bearer(identity.owner_token, path="/api/audit/verify")
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_4_7_audit_api_requires_audit_read(identity):
    denied(identity.bearer(identity.readonly_token, path="/api/audit/events"), "SCOPE_MISSING", 2)


def test_4_8_sponsor_filter_returns_exact_agents_window_in_one_query(identity):
    identity.clock.advance(seconds=1)
    start = identity.clock()
    assert identity.check(identity.agent_a["credential"], "memory.write").status_code == 200
    assert identity.check(identity.agent_b["credential"], "memory.write").status_code == 200
    denied(identity.check(identity.agent_a["credential"], "principals.admin"),
           "PRINCIPAL_CREATION_FORBIDDEN", 6)
    response = identity.bearer(identity.owner_token, path="/api/audit/events", params={
        "sponsor_id": str(identity.partner_a["id"]), "from": start.isoformat(),
        "to": (identity.clock()).isoformat(),
    })
    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 2
    assert {event["outcome"] for event in events} == {"ALLOW", "DENY"}
    assert all(event["principal_id"] == str(identity.agent_a["principal"]["id"]) for event in events)
    assert all(event["sponsor_id"] == str(identity.partner_a["id"]) for event in events)
    # Count only the filtered event-fetch SELECT, not authentication, chain-head
    # lookup or the request's own audit insertion.
    from sqlalchemy import event

    queries = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        normalized = statement.lower()
        if (
            "select" in normalized and "audit_events" in normalized
            and "sponsor_id" in normalized.partition("where")[2]
        ):
            queries.append(statement)

    target = identity.engine.connection or identity.engine.real
    event.listen(target, "before_cursor_execute", capture)
    try:
        repeated = identity.bearer(identity.owner_token, path="/api/audit/events", params={
            "sponsor_id": str(identity.partner_a["id"]), "from": start.isoformat(),
            "to": identity.clock().isoformat(),
        })
        assert repeated.status_code == 200
    finally:
        event.remove(target, "before_cursor_execute", capture)
    assert len(queries) == 1
