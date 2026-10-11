"""Real MCP smoke client. Never prints credentials, headers or session IDs."""

import argparse
import asyncio
import json
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def check(url: str, environment: str, unix_socket: str | None = None):
    token = os.environ.get("CMH_BOOTSTRAP_TOKEN", "")
    if not token:
        raise RuntimeError("CMH_BOOTSTRAP_TOKEN is required")
    transport = httpx.AsyncHTTPTransport(uds=unix_socket) if unix_socket else None
    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, transport=transport,
        ) as http,
        streamable_http_client(url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        initialized = await session.initialize()
        tools = await session.list_tools()
        assert [tool.name for tool in tools.tools] == ["cmh_ping"]
        response = await session.call_tool("cmh_ping", {})
        assert not response.isError
        result = json.loads(response.content[0].text)
        assert result == {
            "server": "cmh", "version": "2.0.0.dev0",
            "principal": "bootstrap", "env": environment,
        }
        print(json.dumps({
            "initialized": initialized.serverInfo.name,
            "tools": [tool.name for tool in tools.tools], "result": result,
        }))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8008/mcp")
    parser.add_argument("--env", default=os.environ.get("CMH_ENV", "dev"))
    parser.add_argument("--unix-socket", help="Use a local Unix socket instead of TCP")
    arguments = parser.parse_args()
    asyncio.run(check(arguments.url, arguments.env, arguments.unix_socket))
