"""Credential revocation must take effect inside an already initialized MCP session."""
import asyncio
import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@pytest.mark.asyncio
async def test_e2e_3_revocation_under_fire(identity):
    agent = identity.agent_a["principal"]
    credential_a = identity.agent_a["credential"]
    credential_b = identity.credential(
        identity.owner_client, agent, "openclaw-agent-standard",
    )
    baseline = identity.audit()[-1]["seq"]
    identity.start_mcp()
    rejected_http = []

    async def response_hook(response):
        if response.status_code == 401:
            await response.aread()
            rejected_http.append(response.json())

    # Keep one SDK session initialized with A across the Owner's revocation.
    # The ASGI auth boundary returns HTTP 401, not a successful tool result.
    try:
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=identity.socket_path),
            headers={"Authorization": "Bearer " + credential_a["token"]},
            event_hooks={"response": [response_hook]},
        ) as http, streamable_http_client(
            "http://configuration.example/mcp", http_client=http,
        ) as streams, ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            before = await session.call_tool("cmh_whoami", {})
            assert before.isError is False
            assert json.loads(before.content[0].text)["principal"] == agent["slug"]
            revoke = identity.request(
                identity.owner_client, "POST",
                f"/admin/api/credentials/{credential_a['id']}/revoke",
            )
            assert revoke.status_code == 200
            await asyncio.wait_for(session.call_tool("cmh_whoami", {}), timeout=10)
            pytest.fail("Revoked credential was accepted in the existing session")
    except* httpx.HTTPStatusError as errors:
        def leaves(group):
            for error in group.exceptions:
                if isinstance(error, BaseExceptionGroup):
                    yield from leaves(error)
                else:
                    yield error
        assert all(error.response.status_code == 401 for error in leaves(errors))
    assert rejected_http == [{"code": "AUTH_REVOKED"}]
    async with identity.mcp(credential_b) as session_b:
        after = await session_b.call_tool("cmh_whoami", {})
    assert after.isError is False
    assert json.loads(after.content[0].text)["principal"] == agent["slug"]
    events = [event for event in identity.audit()
              if event["seq"] > baseline and str(event["principal_id"]) == str(agent["id"])
              and event["operation"] != "mcp.transport"]
    assert [(str(event["credential_id"]), event["operation"], event["outcome"],
             event["decision_trace"]["code"]) for event in events] == [
        (str(credential_a["id"]), "identity.whoami", "ALLOW", "OK"),
        (str(credential_a["id"]), "auth.authenticate", "DENY", "AUTH_REVOKED"),
        (str(credential_b["id"]), "identity.whoami", "ALLOW", "OK"),
    ]
    for event in identity.audit():
        metadata = json.dumps(event["request_meta"], default=str)
        assert credential_a["token"] not in metadata
        assert credential_b["token"] not in metadata
        assert "authorization" not in metadata.lower()
        assert "bearer " not in metadata.lower()
