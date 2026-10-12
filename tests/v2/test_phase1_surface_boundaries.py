"""Additional explicit brief requirements, beyond the original gate rows."""

import secrets
from datetime import timedelta

import pytest
from conftest import SensitiveTestValue
from contract_helpers import denied
from test_phase1_governance import registration


@pytest.mark.parametrize("path", ["system.extra", "inbox.extra", "unapproved.extra"])
def test_namespace_creation_cannot_extend_seed_only_roots(identity, path):
    response = identity.request(identity.owner_client, "POST", "/admin/api/namespaces",
                                json={"path": path})
    denied(response, "NAMESPACE_FORBIDDEN")
    assert not identity.sql("SELECT id FROM namespaces WHERE path=CAST(:path AS ltree)", path=path)


def test_legacy_human_bearer_cannot_register_principal(identity):
    value = SensitiveTestValue(secrets.token_urlsafe(32))
    imported = identity.request(
        identity.owner_client, "POST", "/admin/api/credentials/import",
        json={"principal_id": str(identity.owner["id"]), "name": "legacy-owner-test",
              "token": value},
    )
    assert imported.status_code == 201
    payload = registration(identity)
    response = identity.owner_client.post("/api/principals",
                                         headers={"Authorization": "Bearer " + value},
                                         json=payload)
    denied(response, "AI_CLIENT_CEILING")
    assert not identity.sql("SELECT id FROM principals WHERE slug=:slug", slug=payload["slug"])


def test_approval_list_lazily_expires_old_pending_items(identity):
    payload = registration(identity, kind="agent", role="external", tier=1,
                           sponsor_id=str(identity.owner["id"]), template="external-readonly")
    queued = identity.request(identity.client_a, "POST", "/admin/api/principals", json=payload)
    assert queued.status_code == 202
    identity.tamper("UPDATE approvals SET expires_at=:past WHERE id=:id",
                   past=identity.clock() - timedelta(days=15),
                   id=queued.json()["approval_id"])
    listing = identity.owner_client.get("/admin/api/approvals")
    assert listing.status_code == 200
    found = next(row for row in listing.json()["approvals"]
                 if row["id"] == queued.json()["approval_id"])
    assert found["status"] == "expired"
    assert not identity.sql("SELECT id FROM principals WHERE slug=:slug", slug=payload["slug"])
