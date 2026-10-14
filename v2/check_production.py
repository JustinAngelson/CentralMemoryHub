"""Content-free HTTP/MCP smoke probe; never reads deployment/database secrets."""
import argparse
import asyncio
import getpass
import json
from urllib.parse import urlsplit

import httpx


async def check_url(url, token=None, client=None, mcp_client_factory=None):
    base = urlsplit(url)
    if base.scheme not in {"http", "https"} or not base.netloc or base.username or base.password:
        raise ValueError("HTTP(S) origin required")
    if base.path not in {"", "/"} or base.query or base.fragment:
        raise ValueError("Origin only, no path/query")
    url = url.rstrip("/")
    if client is None:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as owned:
            return await check_url(url, token, owned, mcp_client_factory)
    landing = await client.get(url + "/")
    frames = (landing.headers.get("x-frame-options", "").upper() in {"DENY", "SAMEORIGIN"}
              and "frame-ancestors" in landing.headers.get("content-security-policy", ""))
    invalid = await client.post(url + "/api/waitlist", json={"email": "not-an-email"})
    anonymous = await client.post(url + "/mcp", json={})
    schema = await client.get(url + "/openapi.json")
    checks = {"landing": landing.status_code == 200, "frame_headers": frames,
              "invalid_waitlist": invalid.status_code == 400, "anonymous_mcp": anonymous.status_code == 401,
              "openapi_origin": schema.status_code == 200
              and {"url": url} in schema.json().get("servers", [])}
    if token:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        options = {"httpx_client_factory": mcp_client_factory} if mcp_client_factory else {}
        async with (
            streamablehttp_client(url + "/mcp",
                headers={"Authorization": "Bearer " + token}, **options) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            for name in ("cmh_whoami", "cmh_health_check"):
                result = await session.call_tool(name, {"params": {}} if name.endswith("check") else {})
                checks[name] = not result.isError
    return {"ok": all(checks.values()), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--with-token", action="store_true")
    parser.add_argument("--unix-socket", help="Local rehearsal only")
    args = parser.parse_args()
    try:
        async def run():
            token = getpass.getpass("Token (hidden): ") if args.with_token else None
            if not args.unix_socket:
                return await check_url(args.url, token)
            if urlsplit(args.url).hostname not in {"localhost", "127.0.0.1"}:
                raise ValueError("Unix-socket rehearsal URL must be local")
            def factory(**kwargs):
                return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(
                    uds=args.unix_socket), **kwargs)
            async with factory() as client:
                return await check_url(args.url, token, client, factory)
        result = asyncio.run(run())
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    except Exception as error:  # noqa: BLE001 — never leak credentials or response bodies
        print(json.dumps({"ok": False, "error_type": type(error).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
