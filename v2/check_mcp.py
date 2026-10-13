"""Isolated bootstrap -> session -> credential -> real MCP smoke, without secrets in output."""

import argparse
import asyncio
import json
import os
import re
import secrets
from importlib.resources import files

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def check(url: str, environment: str, unix_socket: str | None = None):
    token = os.environ.get("CMH_BOOTSTRAP_TOKEN", "")
    if len(token) < 64:
        raise RuntimeError("A 64+ character bootstrap secret is required")
    base = url.removesuffix("/mcp")
    transport = httpx.AsyncHTTPTransport(uds=unix_socket) if unix_socket else None
    async with httpx.AsyncClient(transport=transport) as http:
        boot = await http.post(base + "/admin/api/bootstrap", headers={
            "Authorization": "Bearer " + token, "Origin": os.environ.get("CMH_PUBLIC_URL", base),
        }, json={
            "slug": "owner", "display_name": "owner", "email": "owner@example.invalid",
            "password": secrets.token_urlsafe(32),
        })
        if boot.status_code != 201:
            raise RuntimeError("Smoke bootstrap requires a fresh isolated database")
        # Compose's internal loopback HTTP has no TLS; explicitly replay the
        # Secure cookie only in this isolated test, never in an application client.
        value = http.cookies.get("cmh_session")
        if not value:
            raise RuntimeError("Bootstrap did not return an admin session")
        credential = await http.post(base + "/admin/api/credentials", headers={
            "Cookie": "cmh_session=" + value, "Origin": os.environ.get("CMH_PUBLIC_URL", base),
        }, json={
            "principal_id": boot.json()["principal"]["id"], "name": "smoke-ai-client",
            "template": "personal-ai-client",
        })
        if credential.status_code != 201:
            raise RuntimeError("Smoke credential issuance failed")
        owner_bearer = credential.json()["token"]
        agent = await http.post(base + "/admin/api/principals", headers={
            "Cookie": "cmh_session=" + value, "Origin": os.environ.get("CMH_PUBLIC_URL", base),
        }, json={
            "kind": "agent", "slug": "agent-smoke", "display_name": "agent_smoke",
            "tier": 2, "sponsor_id": boot.json()["principal"]["id"],
            "template": "openclaw-agent-standard", "credential_name": "smoke-agent-runtime",
        })
        if agent.status_code != 201:
            raise RuntimeError("Smoke template agent provisioning failed")
        bearer = agent.json()["credential"]["token"]
        agent_id = agent.json()["principal"]["id"]
    transport = httpx.AsyncHTTPTransport(uds=unix_socket) if unix_socket else None
    async with (
        httpx.AsyncClient(headers={"Authorization": "Bearer " + bearer}, transport=transport) as http,
        streamable_http_client(url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        inventory = json.loads(files("cmh.mcp").joinpath("v1_inventory.json").read_text())
        required = {item["name"] for item in inventory["tools"]} | {
            "cmh_ping", "cmh_whoami", "cmh_check_access", "cmh_verify_audit_chain",
        }
        if required != {tool.name for tool in tools.tools}:
            raise RuntimeError("MCP must expose exactly the legacy inventory plus declared metadata tools")
        verified = await session.call_tool("cmh_verify_audit_chain", {})
        if verified.isError or json.loads(verified.content[0].text).get("valid") is not True:
            raise RuntimeError("MCP chain integrity verification failed")
        result = await session.call_tool("cmh_whoami", {})
        if result.isError:
            raise RuntimeError("MCP whoami failed")
        body = json.loads(result.content[0].text)
        if (body["principal"] != "agent-smoke" or body["kind"] != "agent"
                or body["tier"] != 2 or body["sponsor"] != "owner"
                or body["ai_client"] is not False):
            raise RuntimeError("MCP caller identity mismatch")
        stored = await session.call_tool("cmh_store_memory", {"params": {
            "content": "isolated compose smoke memory",
        }})
        if stored.isError or not stored.content[0].text.startswith("Memory stored successfully."):
            raise RuntimeError("MCP memory store failed")
        searched = await session.call_tool("cmh_search_memory", {"params": {"query": "compose smoke"}})
        if searched.isError or "isolated compose smoke memory" not in searched.content[0].text:
            raise RuntimeError("MCP memory search failed")
        memory_id = re.search(r"(?m)^ID: (.+)$", stored.content[0].text).group(1)
        calls = [
            ("cmh_get_memory", {"params": {"id": memory_id}}),
            ("cmh_health_check", {}),
            ("cmh_list_agents", {}),
            ("cmh_list_contexts", {}),
            ("cmh_store_knowledge", {"params": {"term": "compose smoke knowledge"}}),
            ("cmh_search_knowledge", {"params": {"term": "compose smoke"}}),
            ("cmh_log_decision", {"params": {
                "made_by_agent": body["principal"], "context": "compose smoke",
                "decision_text": "use native compatibility",
            }}),
            ("cmh_list_decisions", {"params": {}}),
            ("cmh_create_session", {"params": {"agent_id": agent_id}}),
            ("cmh_list_sessions", {"params": {}}),
            ("cmh_create_memory_link", {"params": {"pinecone_vector_id": memory_id}}),
            ("cmh_list_memory_links", {"params": {"pinecone_vector_id": memory_id}}),
        ]
        for name, payload in calls:
            result = await session.call_tool(name, payload)
            if result.isError:
                raise RuntimeError(f"Compatibility smoke failed: {name}")
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=unix_socket) if unix_socket else None,
        ) as verifier:
            response = await verifier.get(base + "/api/audit/verify", headers={
                "Authorization": "Bearer " + owner_bearer,
            })
        if response.status_code != 200 or not response.json().get("valid"):
            raise RuntimeError("Compatibility smoke audit chain verification failed")
        print(json.dumps({"identity_verified": True, "env": environment,
                          "tools": sorted(required), "bootstrap_session_credential": "ok",
                          "fake_memory_store_search": "ok",
                          "v1_compatibility_tools": 2 + len(calls), "audit_chain": "valid"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8008/mcp")
    parser.add_argument("--env", default=os.environ.get("CMH_ENV", "dev"))
    parser.add_argument("--unix-socket")
    args = parser.parse_args()
    asyncio.run(check(args.url, args.env, args.unix_socket))
