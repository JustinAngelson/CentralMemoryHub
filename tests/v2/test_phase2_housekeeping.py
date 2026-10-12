"""F1–F7: accepted Phase 1 housekeeping, before memory implementation."""

import json
import secrets
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import SensitiveTestValue
from contract_helpers import denied


@pytest.mark.parametrize("kind,template", [
    ("agent", "personal-ai-client"),
    ("agent", "service-integration"),
    ("service", "openclaw-agent-standard"),
])
def test_F1_creation_template_kind_and_role_match(identity, kind, template):
    slug = "wrong-template-" + uuid4().hex[:12]
    response = identity.request(identity.owner_client, "POST", "/admin/api/principals", json={
        "kind": kind, "slug": slug, "role": "delegated_agent", "tier": 2,
        "sponsor_id": str(identity.owner["id"]), "template": template,
    })
    denied(response, "TIER_FORBIDDEN", step=3)
    assert not identity.sql("SELECT id FROM principals WHERE slug=:slug", slug=slug)


@pytest.mark.no_app_operation(reason="Only GET /healthz: unreachable database health probe.")
def test_F2_unreachable_database_role_is_unknown(unreachable_client):
    client, _ = unreachable_client
    result = client.get("/healthz")
    assert result.status_code == 503
    assert result.json()["db_role"] == "unknown"


def test_F4_rotation_obeys_template_expiry(identity):
    name = "personal-ai-client-expiry-" + uuid4().hex[:8]
    result = identity.request(identity.owner_client, "POST", "/admin/api/templates", json={
        "name": name, "scopes": ["bundle:observer"], "default_expiry_days": 17,
    })
    assert result.status_code == 201
    credential = identity.credential(identity.owner_client, identity.owner, name)
    rotated = identity.request(identity.owner_client, "POST",
                               f"/admin/api/credentials/{credential['id']}/rotate")
    assert rotated.status_code == 201
    actual = identity.sql("SELECT expires_at FROM credentials WHERE id=:id",
                          id=rotated.json()["id"])[0]["expires_at"]
    assert actual == identity.clock() + timedelta(days=17)


def test_F4_legacy_rotation_is_refused(identity):
    token = SensitiveTestValue(secrets.token_urlsafe(32))
    created = identity.request(identity.owner_client, "POST", "/admin/api/credentials/import",
                               json={"token": token, "principal_id": identity.owner["id"],
                                     "name": "legacy-test-" + uuid4().hex})
    assert created.status_code == 201
    response = identity.request(identity.owner_client, "POST",
                                f"/admin/api/credentials/{created.json()['id']}/rotate")
    denied(response, "VALIDATION_FAILED")


def test_F5_namespace_creation_scope_and_audit_operation(identity):
    from cmh.auth.context import PrincipalContext
    from cmh.services.administration import namespace_create

    path = "org.f5_" + uuid4().hex[:10]
    result = identity.request(identity.owner_client, "POST", "/admin/api/namespaces",
                              json={"path": path})
    assert result.status_code == 201
    assert identity.audit()[-1]["operation"] == "namespaces.create"
    subject = dict(identity.sql("SELECT * FROM principals WHERE id=:id",
                                id=identity.owner["id"])[0])
    credential = dict(identity.sql("SELECT * FROM credentials WHERE id=:id",
                                   id=identity.owner_token["id"])[0])
    credential.update(ai_client=False, scopes=["principals.admin"])
    context = PrincipalContext(subject, credential)
    rejected = namespace_create(identity.app.state.identity_service, context,
                                {"path": path + ".denied"})
    assert rejected["code"] == "SCOPE_MISSING"
    assert not identity.sql("SELECT id FROM namespaces WHERE path=CAST(:p AS ltree)",
                           p=path + ".denied")


def test_F6_unknown_email_verifies_fixed_dummy_hash(identity, monkeypatch):
    from argon2.exceptions import VerificationError

    import cmh.services.accounts as accounts

    calls = []
    previous = []

    class Spy:
        def verify(self, encoded, password):
            calls.append(encoded.startswith("$argon2id$") and (
                not previous or encoded == previous[0]
            ))
            previous[:] = [encoded]
            raise VerificationError("Synthetic mismatch")

    monkeypatch.setattr(accounts, "password_hasher", lambda: Spy())
    for index in range(2):
        result = identity.request(identity.owner_client, "POST", "/admin/api/login", json={
            "email": f"missing-{index}@example.invalid", "password": identity.password,
        })
        denied(result, "AUTH_INVALID")
    assert calls == [True, True]


@pytest.mark.no_app_operation(reason="Bundle configuration expansion validation; no app operation.")
def test_F7_bundle_constants_match_seed():
    from cmh.policy.scopes import BUNDLES

    config = json.loads((Path(__file__).resolve().parents[2] / "seed/bundles.yaml").read_text())

    def expand(name):
        rule = config[name]
        return (
            (expand(rule["inherits"]) if "inherits" in rule else set())
            | {value + ".read" for value in rule.get("reads", [])}
            | {value + ".write" for value in rule.get("writes", [])}
            | set(rule.get("adds", []))
        )

    assert BUNDLES == {name: expand(name) for name in config}
