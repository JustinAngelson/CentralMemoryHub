"""Isolated bootstrap -> session -> credential -> real MCP smoke, without secrets in output."""

import argparse
import asyncio
import json
import os
import secrets

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
        bearer = credential.json()["token"]
    transport = httpx.AsyncHTTPTransport(uds=unix_socket) if unix_socket else None
    async with (
        httpx.AsyncClient(headers={"Authorization": "Bearer " + bearer}, transport=transport) as http,
        streamable_http_client(url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        required = {"cmh_ping", "cmh_whoami", "cmh_check_access", "cmh_register_agent"}
        if not required <= {tool.name for tool in tools.tools}:
            raise RuntimeError("Missing Phase 1 MCP tools")
        result = await session.call_tool("cmh_whoami", {})
        if result.isError:
            raise RuntimeError("MCP whoami failed")
        body = json.loads(result.content[0].text)
        if body["principal"] != "owner" or body["ai_client"] is not True:
            raise RuntimeError("MCP caller identity mismatch")
        print(json.dumps({"identity_verified": True, "env": environment,
                          "tools": sorted(required), "bootstrap_session_credential": "ok"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8008/mcp")
    parser.add_argument("--env", default=os.environ.get("CMH_ENV", "dev"))
    parser.add_argument("--unix-socket")
    args = parser.parse_args()
    asyncio.run(check(args.url, args.env, args.unix_socket))
