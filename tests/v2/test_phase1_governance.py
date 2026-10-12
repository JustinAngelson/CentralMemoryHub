"""Gate §2A: principals, sponsor ceilings, templates and private grants."""

import json
import secrets

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from test_phase1_credentials import denied


def registration(case, **extra):
    return {
        "kind": "agent", "slug": "agent-test-" + secrets.token_hex(4),
        "display_name": "agent_nix_test", "tier": 2,
        "sponsor_id": str(case.partner_a["id"]),
        "template": "openclaw-agent-standard", "credential_name": "test-runtime", **extra,
    }


def grant(case, client, principal, namespace, permission="read"):
    return case.request(client, "POST", "/admin/api/grants", json={
        "principal_id": str(principal["id"]), "namespace": namespace,
        "permission": permission,
    })


def test_2A_1_missing_sponsor_rejected_by_service_and_schema(identity):
    response = identity.request(identity.owner_client, "POST", "/admin/api/principals",
                                json=registration(identity, sponsor_id=None))
    assert response.status_code in (403, 422)
    with identity.engine.begin() as connection:
        with pytest.raises(IntegrityError) as error, connection.begin_nested():
            connection.execute(text(
                "INSERT INTO principals "
                "(id,kind,slug,display_name,role,tier,status,created_by,created_at) "
                "VALUES (gen_random_uuid(),'agent','agent-no-sponsor',"
                "'agent_nix_test','delegated_agent',2,'active',:owner,now())"
            ), {"owner": identity.owner["id"]})
        assert error.value.orig.sqlstate == "23514"


def test_2A_2_agent_tier_cannot_exceed_sponsor(identity):
    identity.tamper("UPDATE principals SET tier=1 WHERE id=:id", id=identity.partner_a["id"])
    response = identity.request(identity.owner_client, "POST", "/admin/api/principals",
                                json=registration(identity, tier=2))
    denied(response, "SPONSOR_CEILING")


def test_2A_3_agent_cannot_be_tier_four(identity):
    response = identity.request(identity.owner_client, "PATCH",
                                f"/admin/api/principals/{identity.agent_a['principal']['id']}",
                                json={"tier": 4})
    denied(response, "AGENT_TIER_LIMIT")


def test_2A_4_grant_outside_sponsor_envelope(identity):
    other_private = "people." + identity.partner_b["slug"] + ".private"
    denied(grant(identity, identity.owner_client, identity.agent_a["principal"], other_private),
           "SPONSOR_CEILING")


def test_2A_5_live_sponsor_grant_revocation(identity):
    assert identity.check(identity.agent_a["credential"]).status_code == 200
    response = identity.request(identity.owner_client, "DELETE", "/admin/api/grants", json={
        "principal_id": str(identity.partner_a["id"]), "namespace": "org",
    })
    assert response.status_code == 200
    denied(identity.check(identity.agent_a["credential"]), "SPONSOR_CEILING")


def test_2A_6_inactive_sponsor_suspends_all_dependents(identity):
    response = identity.request(identity.owner_client, "PATCH",
                                f"/admin/api/principals/{identity.partner_a['id']}",
                                json={"status": "inactive"})
    assert response.status_code == 200
    rows = identity.sql("SELECT status FROM principals WHERE sponsor_id=:id",
                        id=identity.partner_a["id"])
    assert rows and all(row["status"] == "suspended" for row in rows)
    denied(identity.bearer(identity.agent_a["credential"]), "PRINCIPAL_SUSPENDED")


def test_2A_7_partner_template_creates_principal_credential_and_notification(identity):
    response = identity.request(identity.client_a, "POST", "/admin/api/principals",
                                json=registration(identity))
    assert response.status_code == 201
    created = response.json()
    principal = created["principal"]
    assert str(principal["sponsor_id"]) == str(identity.partner_a["id"])
    assert principal["kind"] == "agent"
    assert created["credential"]["template_id"]
    assert identity.sql(
        "SELECT id FROM namespaces WHERE path::text=:path",
        path="agents." + principal["slug"] + ".private",
    )
    assert identity.sql(
        "SELECT id FROM notifications WHERE recipient_principal_id=:id "
        "AND payload::text LIKE :principal",
        id=identity.owner["id"], principal="%" + str(principal["id"]) + "%",
    )
    with identity.engine.connect() as connection:
        audit = connection.execute(text(
            "SELECT decision_trace FROM audit_events ORDER BY seq DESC LIMIT 1"
        )).scalar_one()
    assert str(created["credential"]["template_id"]) in json.dumps(audit)


def test_2A_8_partner_cannot_choose_another_sponsor(identity):
    response = identity.request(identity.client_a, "POST", "/admin/api/principals",
                                json=registration(identity, sponsor_id=str(identity.partner_b["id"])))
    assert response.status_code == 403


def test_2A_9_external_template_queues_without_issuing(identity):
    payload = registration(identity, kind="agent", role="external", tier=1,
                           sponsor_id=str(identity.owner["id"]), template="external-readonly")
    response = identity.request(identity.client_a, "POST", "/admin/api/principals", json=payload)
    assert response.status_code == 202
    assert response.json()["outcome"] == "QUEUE"
    assert response.json()["approval_id"]
    assert not identity.sql("SELECT id FROM principals WHERE slug=:slug", slug=payload["slug"])
    assert not identity.sql(
        "SELECT id FROM credentials WHERE name=:name", name=payload["credential_name"]
    )


def test_2A_10_partner_cannot_edit_template(identity):
    response = identity.request(identity.client_a, "PATCH",
                                "/admin/api/templates/openclaw-agent-standard",
                                json={"scopes": ["principals.admin"]})
    assert response.status_code == 403


@pytest.mark.parametrize("forced", [False, True])
@pytest.mark.parametrize("operation", ["principals.admin", "credentials.issue_sponsored"])
def test_2A_11_I3_precedes_scope_even_with_forced_admin_scopes(identity, forced, operation):
    token = identity.agent_a["credential"]
    if forced:
        identity.tamper("UPDATE credentials SET scopes=:scopes WHERE id=:id",
                        id=token["id"], scopes=[
                            "principals.admin", "credentials.issue_sponsored",
                        ])
    denied(identity.check(token, operation), "PRINCIPAL_CREATION_FORBIDDEN", 6)
    response = identity.bearer(token, "POST", "/api/principals",
                               json=registration(identity))
    denied(response, "PRINCIPAL_CREATION_FORBIDDEN", 6)


@pytest.mark.asyncio
async def test_2A_11_mcp_register_agent_denies_I3(identity):
    result, body = await identity.tool(
        identity.agent_a["credential"], "cmh_register_agent", registration(identity)
    )
    assert result.isError
    assert body["code"] == "PRINCIPAL_CREATION_FORBIDDEN"
    assert body["step"] == 6


def test_2A_12_agent_access_audit_carries_sponsor(identity):
    response = identity.check(identity.agent_a["credential"])
    assert response.status_code == 200
    with identity.engine.connect() as connection:
        event = connection.execute(text(
            "SELECT principal_id,sponsor_id FROM audit_events ORDER BY seq DESC LIMIT 1"
        )).mappings().one()
    assert str(event["principal_id"]) == str(identity.agent_a["principal"]["id"])
    assert str(event["sponsor_id"]) == str(identity.partner_a["id"])


@pytest.mark.parametrize("permission", ["read", "write"])
def test_2A_13_partner_can_grant_own_private_to_own_sponsored_agent(identity, permission):
    namespace = "people." + identity.partner_a["slug"] + ".private"
    response = grant(identity, identity.client_a, identity.agent_a["principal"],
                     namespace, permission)
    assert response.status_code == 201
    assert identity.check(identity.agent_a["credential"], "memory.read", namespace).status_code == 200


@pytest.mark.parametrize("other_agent", [False, True])
def test_2A_14_partner_cannot_make_ad_hoc_org_or_other_agent_grants(identity, other_agent):
    agent = identity.agent_b["principal"] if other_agent else identity.agent_a["principal"]
    namespace = ("people." + identity.partner_a["slug"] + ".private") if other_agent else (
        "org.clients"
    )
    assert grant(identity, identity.client_a, agent, namespace).status_code == 403


def test_2A_15_sync_service_owner_only(identity):
    payload = registration(identity, kind="service", role=None, tier=None,
                           sponsor_id=str(identity.owner["id"]),
                           template="service-integration", scopes=["bundle:sync"])
    response = identity.request(identity.owner_client, "POST", "/admin/api/principals", json=payload)
    assert response.status_code == 201
    assert "entities.write" in response.json()["credential"]["scopes"]
    assert any(scope.startswith("sync.") for scope in response.json()["credential"]["scopes"])
    payload["slug"] = "sync-service-" + secrets.token_hex(4)
    assert identity.request(identity.client_a, "POST", "/admin/api/principals",
                            json=payload).status_code == 403


def test_2A_16_partner_personal_client_self_only(identity):
    own = identity.credential(identity.client_a, identity.partner_a, "personal-ai-client")
    assert identity.bearer(own).json()["principal"] == identity.partner_a["slug"]
    response = identity.request(identity.client_a, "POST", "/admin/api/credentials", json={
        "principal_id": str(identity.partner_b["id"]), "template": "personal-ai-client",
        "name": "other-human-client",
    })
    assert response.status_code == 403


def test_2A_17_owner_can_issue_for_another_human(identity):
    credential = identity.credential(identity.owner_client, identity.partner_b, "personal-ai-client")
    response = identity.bearer(credential)
    assert response.status_code == 200
    assert response.json()["principal"] == identity.partner_b["slug"]


def test_T1_13_expired_approval_never_executes_payload(identity):
    payload = registration(identity, kind="agent", role="external", tier=1,
                           sponsor_id=str(identity.owner["id"]), template="external-readonly")
    response = identity.request(identity.client_a, "POST", "/admin/api/principals", json=payload)
    assert response.status_code == 202
    approval_id = response.json()["approval_id"]
    identity.clock.advance(days=14, seconds=1)
    response = identity.request(identity.owner_client, "POST",
                                f"/admin/api/approvals/{approval_id}/approve")
    assert response.status_code in (403, 409)
    assert identity.sql("SELECT status FROM approvals WHERE id=:id",
                        id=approval_id)[0]["status"] == "expired"
    assert not identity.sql("SELECT id FROM principals WHERE slug=:slug", slug=payload["slug"])


def test_sponsor_reassignment_reactivates_suspended_agent(identity):
    agent = identity.agent_a["principal"]
    assert identity.request(identity.owner_client, "PATCH",
                            f"/admin/api/principals/{identity.partner_a['id']}",
                            json={"status": "inactive"}).status_code == 200
    denied(identity.bearer(identity.agent_a["credential"]), "PRINCIPAL_SUSPENDED")
    assert identity.request(identity.owner_client, "PATCH",
                            f"/admin/api/principals/{agent['id']}",
                            json={"sponsor_id": str(identity.partner_b["id"])}).status_code == 200
    assert identity.bearer(identity.agent_a["credential"]).status_code == 200
