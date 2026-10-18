"""Only the exact /mcp/ alias is normalized, before authentication and dispatch."""
import json
from datetime import timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def assert_metadata(identity, baseline, secret):
    events = [event for event in identity.audit() if event["seq"] > baseline]
    assert events
    for event in events:
        metadata = event["request_meta"]
        assert metadata["route"] == "/mcp"
        assert metadata["route_alias"] == "/mcp/"
        serialized = json.dumps(metadata, default=str)
        assert secret not in serialized
        assert "authorization" not in serialized.lower()
        assert "bearer " not in serialized.lower()
    return events


@pytest.mark.asyncio
async def test_alias_real_sdk_initialize_and_whoami(identity):
    credential = identity.agent_a["credential"]
    baseline = identity.audit()[-1]["seq"]
    identity.start_mcp()
    statuses = []

    async def response_hook(response):
        statuses.append(response.status_code)

    async with (
        httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=identity.socket_path),
            headers={"Authorization": "Bearer " + credential["token"]},
            event_hooks={"response": [response_hook]},
            timeout=10,
        ) as http,
        streamable_http_client(
            "http://configuration.example/mcp/", http_client=http,
        ) as streams,
        ClientSession(
            streams[0], streams[1], read_timeout_seconds=timedelta(seconds=10),
        ) as session,
    ):
        await session.initialize()
        result = await session.call_tool("cmh_whoami", {})
    assert result.isError is False
    assert json.loads(result.content[0].text)["principal"] == identity.agent_a["principal"]["slug"]
    assert statuses and not any(300 <= status < 400 for status in statuses)
    events = assert_metadata(identity, baseline, credential["token"])
    assert any(event["operation"] == "identity.whoami" for event in events)


def test_alias_missing_auth_matches_canonical_challenge(identity):
    canonical = identity.owner_client.post("/mcp", json={}, follow_redirects=False)
    baseline = identity.audit()[-1]["seq"]
    alias = identity.owner_client.post("/mcp/", json={}, follow_redirects=False)
    assert canonical.status_code == alias.status_code == 401
    assert canonical.json() == alias.json() == {"code": "AUTH_MISSING"}
    assert canonical.headers["www-authenticate"] == alias.headers["www-authenticate"]
    assert_metadata(identity, baseline, identity.agent_a["credential"]["token"])


def test_alias_revoked_credential(identity):
    credential = identity.agent_a["credential"]
    revoke = identity.request(
        identity.owner_client, "POST", f"/admin/api/credentials/{credential['id']}/revoke",
    )
    assert revoke.status_code == 200
    baseline = identity.audit()[-1]["seq"]
    response = identity.owner_client.post(
        "/mcp/", headers={"Authorization": "Bearer " + credential["token"]},
        json={}, follow_redirects=False,
    )
    assert response.status_code == 401
    assert response.json() == {"code": "AUTH_REVOKED"}
    assert_metadata(identity, baseline, credential["token"])


def test_alias_rejects_host(identity):
    credential = identity.agent_a["credential"]
    baseline = identity.audit()[-1]["seq"]
    response = identity.owner_client.post(
        "/mcp/", headers={"Authorization": "Bearer " + credential["token"],
                          "Host": "untrusted.example"},
        json={}, follow_redirects=False,
    )
    assert response.status_code == 421
    assert response.json() == {"code": "HOST_REJECTED"}
    assert_metadata(identity, baseline, credential["token"])


def test_alias_query_key_never_authenticates_or_enters_audit(identity):
    credential = identity.agent_a["credential"]
    baseline = identity.audit()[-1]["seq"]
    response = identity.owner_client.post(
        "/mcp/", params={"key": credential["token"]}, json={}, follow_redirects=False,
    )
    assert response.status_code == 401
    assert response.json() == {"code": "AUTH_MISSING"}
    events = assert_metadata(identity, baseline, credential["token"])
    assert all("?" not in event["request_meta"]["route"] for event in events)


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
@pytest.mark.parametrize("authenticated", [False, True])
def test_exact_endpoints_never_redirect(identity, path, authenticated):
    credential = identity.agent_a["credential"]
    headers = {"Authorization": "Bearer " + credential["token"]} if authenticated else {}
    response = identity.owner_client.post(
        path, headers=headers, json={}, follow_redirects=False,
    )
    assert not 300 <= response.status_code < 400
    assert response.status_code not in (404, 405)
    if not authenticated:
        assert response.status_code == 401


@pytest.mark.parametrize("path", ["/mcp//", "/mcp/mcp", "/mcp/unknown"])
@pytest.mark.parametrize("authenticated", [False, True])
def test_other_mcp_paths_remain_not_found(identity, path, authenticated):
    credential = identity.agent_a["credential"]
    baseline = identity.audit()[-1]["seq"]
    headers = {"Authorization": "Bearer " + credential["token"]} if authenticated else {}
    response = identity.owner_client.post(
        path, headers=headers, json={}, follow_redirects=False,
    )
    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND"}
    events = [event for event in identity.audit() if event["seq"] > baseline]
    assert events
    for event in events:
        assert event["operation"] == "routing.not_found"
        assert event["request_meta"]["route"] == path
        assert "route_alias" not in event["request_meta"]
        assert credential["token"] not in json.dumps(event["request_meta"], default=str)
