"""Gate §1 credentials and caller identity; no record APIs from later phases."""

import asyncio
import json
import secrets
from datetime import timedelta

import pytest
from contract_helpers import denied
from identity_fixtures import require, token_hash


def test_1_4_expired_credential(identity):
    identity.tamper("UPDATE credentials SET expires_at=:at WHERE id=:id",
                    at=identity.clock() - timedelta(seconds=1), id=identity.owner_token["id"])
    denied(identity.bearer(identity.owner_token), "AUTH_EXPIRED")


def test_1_5_revocation_effective_next_call(identity):
    assert identity.bearer(identity.owner_token).status_code == 200
    result = identity.request(identity.owner_client, "POST",
                              f"/admin/api/credentials/{identity.owner_token['id']}/revoke")
    assert result.status_code == 200
    denied(identity.bearer(identity.owner_token), "AUTH_REVOKED")


def test_1_6_inactive_principal(identity):
    identity.tamper("UPDATE principals SET status='inactive' WHERE id=:id",
                    id=identity.agent_a["principal"]["id"])
    denied(identity.bearer(identity.agent_a["credential"]), "PRINCIPAL_INACTIVE")


def test_1_8_rate_limit_is_per_credential(identity):
    first = identity.agent_a["credential"]
    other = identity.agent_b["credential"]
    identity.tamper("UPDATE credentials SET rate_limit=2 WHERE id=:id", id=first["id"])
    assert identity.bearer(first).status_code == 200
    assert identity.bearer(first).status_code == 200
    response = identity.bearer(first)
    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert int(response.headers["Retry-After"]) > 0
    assert identity.bearer(other).status_code == 200


def test_1_10_last_used_advances_at_most_once_per_minute(identity):
    credential = identity.owner_token
    before = identity.sql("SELECT last_used_at FROM credentials WHERE id=:id",
                          id=credential["id"])[0]["last_used_at"]
    assert identity.bearer(credential).status_code == 200
    first = identity.sql("SELECT last_used_at FROM credentials WHERE id=:id",
                         id=credential["id"])[0]["last_used_at"]
    assert first is not None
    assert before is None or first > before
    identity.clock.advance(seconds=30)
    assert identity.bearer(credential).status_code == 200
    assert identity.sql("SELECT last_used_at FROM credentials WHERE id=:id",
                        id=credential["id"])[0]["last_used_at"] == first
    identity.clock.advance(seconds=31)
    assert identity.bearer(credential).status_code == 200
    assert identity.sql("SELECT last_used_at FROM credentials WHERE id=:id",
                        id=credential["id"])[0]["last_used_at"] > first


@pytest.mark.parametrize("field", ["principal", "agent_id", "gpt_role", "author"])
@pytest.mark.asyncio
async def test_1_11_spoofed_identity_is_ignored_or_rejected(identity, field):
    credential = identity.agent_a["credential"]
    principal = identity.agent_a["principal"]
    async with identity.mcp(credential) as session:
        result = await session.call_tool("cmh_check_access", {
            "operation": "memory.write", "namespace": "org", field: "partner_b",
        })
        if not result.isError:
            assert json.loads(result.content[0].text)["outcome"] == "ALLOW"
    event = identity.body_audit()[-1]
    assert str(event["principal_id"]) == str(principal["id"])
    assert str(event["credential_id"]) == str(credential["id"])
    require("partner_b" not in json.dumps(event["request_meta"]), "Spoofed identity was trusted")


def test_1_12_revoke_one_credential_not_its_sibling(identity):
    revoked = identity.owner_token
    sibling = identity.credential(identity.owner_client, identity.owner, "personal-ai-client")
    response = identity.request(identity.owner_client, "POST",
                                f"/admin/api/credentials/{revoked['id']}/revoke")
    assert response.status_code == 200
    denied(identity.bearer(revoked), "AUTH_REVOKED")
    assert identity.bearer(sibling).status_code == 200


@pytest.mark.asyncio
async def test_1_13_personal_client_has_human_principal_and_actor(identity):
    token = identity.owner_token
    require(token["token"].startswith("cmh_pk_"), "Wrong personal credential prefix")
    result, body = await identity.tool(token, "cmh_whoami", {})
    assert not result.isError
    assert body["principal"] == "owner"
    assert body["kind"] == "human"
    assert body["actor"] == token["name"]
    assert body["credential_kind"] == "personal_ai_client"
    assert body["ai_client"] is True
    event = identity.body_audit()[-1]
    assert str(event["principal_id"]) == str(identity.owner["id"])
    assert event["actor"] == token["name"]
    require(token["token"] not in json.dumps(body), "whoami returned plaintext credential")


@pytest.mark.parametrize("operation", ["policy.write", "credentials.admin"])
def test_1_14_owner_ai_client_cannot_change_governance(identity, operation):
    denied(identity.check(identity.owner_token, operation), "AI_CLIENT_CEILING", 2)


def test_1_15_readonly_personal_client_cannot_write(identity):
    denied(identity.check(identity.readonly_token), "SCOPE_MISSING", 2)


def test_1_16_synthetic_legacy_cutover_credential(identity):
    # Never import v1's actual shared token during Phase 1.
    token = secrets.token_urlsafe(32)
    response = identity.request(identity.owner_client, "POST", "/admin/api/credentials/import",
                                json={"kind": "legacy_shared", "token": token,
                                      "principal_id": str(identity.owner["id"]),
                                      "name": "synthetic-cutover"})
    assert response.status_code == 201
    credential = {"id": response.json()["id"], "token": token}
    assert identity.bearer(credential).status_code == 200
    require(identity.sql("SELECT token_hash FROM credentials WHERE id=:id",
                         id=credential["id"])[0]["token_hash"] == token_hash(token),
            "Legacy credential was not stored hash-only")
    response = identity.request(identity.owner_client, "POST",
                                f"/admin/api/credentials/{credential['id']}/revoke")
    assert response.status_code == 200
    denied(identity.bearer(credential), "AUTH_REVOKED")


@pytest.mark.asyncio
async def test_phase0_T0_7_replacement_real_mcp_client(identity):
    async with identity.mcp(identity.agent_a["credential"]) as session:
        tools = await session.list_tools()
        names = {tool.name for tool in tools.tools}
        assert {"cmh_ping", "cmh_whoami", "cmh_check_access", "cmh_register_agent"} <= names
        ping = await session.call_tool("cmh_ping", {})
        assert not ping.isError
        assert json.loads(ping.content[0].text) == {
            "server": "cmh", "version": "2.0.0.dev0",
            "principal": identity.agent_a["principal"]["slug"], "env": "test",
        }


@pytest.mark.asyncio
async def test_phase0_T0_9_replacement_concurrent_principal_isolation(identity):
    identity.start_mcp()

    async def probe(agent):
        async with identity.mcp(agent["credential"]) as session:
            for _ in range(8):
                await asyncio.sleep(0)
                result = await session.call_tool("cmh_whoami", {})
                assert not result.isError
                assert json.loads(result.content[0].text)["principal"] == agent["principal"]["slug"]

    await asyncio.gather(probe(identity.agent_a), probe(identity.agent_b))
    assert identity.app.state.mcp.settings.stateless_http is True
