"""Independent review regressions: A2 disclosure and amendment A10 access."""

import json

import pytest
from contract_helpers import denied
from test_phase1_governance import registration


def external_payload(identity, **extra):
    return registration(identity, role="external", tier=1,
                        sponsor_id=str(identity.owner["id"]), template="external-readonly",
                        **extra)


def approve_principal(identity, payload):
    queued = identity.request(identity.owner_client, "POST", "/admin/api/principals", json=payload)
    assert queued.status_code == 202
    response = identity.request(identity.owner_client, "POST",
                               f"/admin/api/approvals/{queued.json()['approval_id']}/approve")
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("caller", ["external", "agent_a1"])
@pytest.mark.parametrize("kind", ["people", "agents"])
def test_A2_existing_and_missing_private_siblings_are_indistinguishable(identity, caller, kind):
    token = approve_principal(identity, external_payload(identity))["credential"] if (
        caller == "external"
    ) else identity.agent_a["credential"]
    slug = identity.partner_b["slug"] if kind == "people" else (
        identity.agent_b["principal"]["slug"]
    )
    existing = identity.check(token, "memory.read", f"{kind}.{slug}.private")
    missing = identity.check(token, "memory.read", f"{kind}.{slug}.absent")
    denied(existing, "NAMESPACE_FORBIDDEN", step=5)
    denied(missing, "NAMESPACE_FORBIDDEN", step=5)
    assert (existing.json()["code"], existing.json()["step"]) == (
        missing.json()["code"], missing.json()["step"],
    )


@pytest.mark.parametrize("invalid", ["write", "people", "agents", "system", "inbox", "missing"])
@pytest.mark.parametrize("at_approval", [False, True])
def test_external_grants_validated_before_queue_and_again_at_approval(identity, invalid, at_approval):
    path = {
        "write": "org.clients", "people": "people." + identity.partner_b["slug"] + ".private",
        "agents": "agents." + identity.agent_b["principal"]["slug"] + ".private",
        "system": "system", "inbox": "inbox", "missing": "org.clients.absent-review",
    }[invalid]
    grant = {"path": path, "access": "write" if invalid == "write" else "read"}
    payload = external_payload(identity, namespace_grants=[grant])
    if at_approval:
        safe = {**payload, "namespace_grants": [{"path": "org.clients", "access": "read"}]}
        queued = identity.request(identity.owner_client, "POST", "/admin/api/principals", json=safe)
        assert queued.status_code == 202
        identity.tamper("UPDATE approvals SET payload=CAST(:payload AS jsonb) WHERE id=:id",
                        payload=json.dumps(payload), id=queued.json()["approval_id"])
        response = identity.request(identity.owner_client, "POST",
                                    f"/admin/api/approvals/{queued.json()['approval_id']}/approve")
    else:
        response = identity.request(identity.owner_client, "POST", "/admin/api/principals",
                                    json=payload)
    assert response.status_code == 403
    assert response.json()["outcome"] == "DENY"
    assert not identity.sql("SELECT id FROM principals WHERE slug=:slug", slug=payload["slug"])
    assert not identity.sql("SELECT id FROM credentials WHERE name=:name",
                           name=payload["credential_name"])
    if not at_approval:
        assert not identity.sql("SELECT id FROM approvals WHERE payload->>'slug'=:slug",
                               slug=payload["slug"])


def service(identity):
    return approve_principal(identity, registration(
        identity, kind="service", role=None, tier=None,
        sponsor_id=str(identity.partner_a["id"]), template="service-integration",
        scopes=["bundle:observer"],
    ))["principal"]


def test_partner_cannot_issue_sync_scopes_for_own_sponsored_service(identity):
    target = service(identity)
    before = identity.sql("SELECT id FROM credentials WHERE principal_id=:id", id=target["id"])
    response = identity.request(identity.client_a, "POST", "/admin/api/credentials", json={
        "principal_id": target["id"], "template": "service-integration",
        "name": "forbidden-sync", "scopes": ["bundle:sync"],
    })
    assert response.status_code == 403
    assert response.json()["outcome"] == "DENY"
    assert identity.sql("SELECT id FROM credentials WHERE principal_id=:id", id=target["id"]) == before
    assert not identity.sql("SELECT id FROM approvals WHERE payload->>'name'='forbidden-sync'")


@pytest.mark.parametrize("target_kind,template", [
    ("agent", "service-integration"), ("service", "openclaw-agent-standard"),
    ("human", "external-readonly"), ("agent", "external-readonly"),
])
def test_credential_template_must_match_target_kind_and_role(identity, target_kind, template):
    target = service(identity) if target_kind == "service" else (
        identity.partner_a if target_kind == "human" else identity.agent_a["principal"]
    )
    before = identity.sql("SELECT id FROM credentials WHERE principal_id=:id", id=target["id"])
    response = identity.request(identity.owner_client, "POST", "/admin/api/credentials", json={
        "principal_id": str(target["id"]), "template": template, "name": "wrong-template",
    })
    denied(response, "TIER_FORBIDDEN", step=3)
    assert identity.sql("SELECT id FROM credentials WHERE principal_id=:id", id=target["id"]) == before


def test_personal_template_name_cannot_bypass_declared_target_role(identity):
    identity.tamper("""
      UPDATE credential_templates SET target_role='external' WHERE name='personal-ai-client'
    """)
    try:
        response = identity.request(identity.owner_client, "POST", "/admin/api/credentials", json={
            "principal_id": str(identity.owner["id"]), "template": "personal-ai-client",
            "name": "wrong-personal-role",
        })
        denied(response, "TIER_FORBIDDEN", step=3)
        assert not identity.sql("SELECT id FROM credentials WHERE name='wrong-personal-role'")
    finally:
        identity.tamper("""
          UPDATE credential_templates SET target_role=NULL WHERE name='personal-ai-client'
        """)


@pytest.mark.parametrize("scopes", [["bundle:sync", "bundle:observer"], ["bundle:observer"]])
def test_service_scope_overrides_are_owner_only_and_sync_cannot_be_combined(identity, scopes):
    target = service(identity)
    client = identity.owner_client if "bundle:sync" in scopes else identity.client_a
    response = identity.request(client, "POST", "/admin/api/credentials", json={
        "principal_id": target["id"], "template": "service-integration",
        "name": "forbidden-override", "scopes": scopes,
    })
    assert response.status_code == 403
    assert not identity.sql("SELECT id FROM credentials WHERE name='forbidden-override'")
    assert not identity.sql("SELECT id FROM approvals WHERE payload->>'name'='forbidden-override'")


@pytest.fixture
def live_role_health_client(role_login_engine):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from cmh.api.health import health_router
    from cmh.db.roles import guard_runtime_role

    guard_runtime_role(role_login_engine, "dev")
    app = FastAPI()
    app.include_router(health_router(role_login_engine, "dev"))
    with TestClient(app) as client:
        yield client


@pytest.mark.no_app_operation(reason="Only GET /healthz: live role guard health probe; no operation.")
def test_health_role_rechecks_privileges_after_startup(identity, live_role_health_client):
    assert live_role_health_client.get("/healthz").json()["db_role"] == "ok"
    identity.tamper("GRANT UPDATE ON audit_events TO cmh_app")
    try:
        unhealthy = live_role_health_client.get("/healthz")
        assert unhealthy.status_code == 503
        assert "audit mutation privileges" in unhealthy.json()["db_role"]
    finally:
        identity.tamper("REVOKE UPDATE ON audit_events FROM cmh_app")
    assert live_role_health_client.get("/healthz").json()["db_role"] == "ok"


def test_unknown_mcp_paths_share_failed_auth_audit_budget(identity):
    before = len(identity.audit())
    statuses = [
        identity.owner_client.post("/mcp/unknown-" + str(i), json={}).status_code
        for i in range(50)
    ]
    assert set(statuses) <= {404, 429}
    events = identity.audit()[before:]
    assert 1 <= len(events) <= 31
    assert sum(row["operation"] == "auth.rate_limit_summary" for row in events) <= 1


@pytest.mark.parametrize("operation", ["memory.read", "memory.write"])
def test_A10_ancestor_org_grant_does_not_reach_finance_or_descendants(identity, operation):
    assert identity.request(identity.owner_client, "POST", "/admin/api/namespaces",
                            json={"path": "org.finance.review-" + identity.partner_a["slug"]}).status_code == 201
    for path in ("org.finance", "org.finance.review-" + identity.partner_a["slug"]):
        denied(identity.check(identity.agent_a["credential"], operation, path),
               "NAMESPACE_FORBIDDEN", step=5)
    claims = identity.bearer(identity.agent_a["credential"]).json()
    assert not any(grant["namespace"] == "org.finance" or
                   grant["namespace"].startswith("org.finance.") for grant in claims["grants"])


def test_A10_explicit_finance_grant_reaches_personal_client(identity):
    response = identity.request(identity.owner_client, "POST", "/admin/api/grants", json={
        "principal_id": str(identity.partner_a["id"]), "namespace": "org.finance",
        "permission": "write",
    })
    assert response.status_code == 201
    personal = identity.credential(identity.client_a, identity.partner_a, "personal-ai-client")
    assert identity.check(personal, "memory.write", "org.finance").json()["outcome"] == "ALLOW"
    assert identity.check(identity.agent_a["credential"], "memory.write", "org.finance").json()[
        "code"
    ] == "NAMESPACE_FORBIDDEN"
