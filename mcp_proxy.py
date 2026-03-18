"""
MCP Proxy — WSGI middleware

Intercepts /mcp requests at the WSGI layer (before Werkzeug touches
headers) and forwards them to the FastMCP server on port 8000.

This approach avoids Werkzeug 3.x strict header validation, which
rejects 'mcp-session-id' when processed as a Flask route.

Applied in app.py:  app.wsgi_app = MCPProxyMiddleware(app.wsgi_app)
"""
import logging
import urllib.request
import urllib.error

MCP_INTERNAL_URL = "http://localhost:8000/mcp"

# Headers forwarded from client → MCP server
REQUEST_PASSTHROUGH = {
    "content-type",
    "accept",
    "mcp-session-id",
    "last-event-id",
}

# Headers forwarded from MCP server → client
RESPONSE_PASSTHROUGH = {
    "content-type",
    "mcp-session-id",
    "cache-control",
    "transfer-encoding",
}

CORS_HEADERS = [
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Methods", "POST, GET, DELETE, OPTIONS"),
    ("Access-Control-Allow-Headers", "Content-Type, Accept, mcp-session-id, Last-Event-ID"),
    ("Access-Control-Expose-Headers", "mcp-session-id"),
]


class MCPProxyMiddleware:
    """WSGI middleware that proxies /mcp to the FastMCP server on port 8000."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")

        if path != "/mcp":
            return self.wsgi_app(environ, start_response)

        method = environ.get("REQUEST_METHOD", "GET")

        # CORS preflight
        if method == "OPTIONS":
            headers = list(CORS_HEADERS) + [("Content-Length", "0")]
            start_response("204 No Content", headers)
            return [b""]

        # Build forwarded headers from WSGI environ
        forward_headers = {}
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                # WSGI converts "mcp-session-id" → "HTTP_MCP_SESSION_ID"
                header_name = key[5:].replace("_", "-").lower()
                if header_name in REQUEST_PASSTHROUGH:
                    forward_headers[header_name] = value
            elif key == "CONTENT_TYPE" and environ.get("CONTENT_TYPE"):
                forward_headers["content-type"] = environ["CONTENT_TYPE"]

        if "accept" not in forward_headers:
            forward_headers["accept"] = "application/json, text/event-stream"

        # Read request body
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(content_length) if content_length > 0 else b""

        try:
            req = urllib.request.Request(
                MCP_INTERNAL_URL,
                data=body if body else None,
                headers={k: v for k, v in forward_headers.items()},
                method=method,
            )

            with urllib.request.urlopen(req, timeout=60) as resp:
                status_code = resp.status
                status_text = resp.reason

                # Build response headers
                response_headers = list(CORS_HEADERS)
                for key, value in resp.headers.items():
                    if key.lower() in RESPONSE_PASSTHROUGH:
                        response_headers.append((key, value))

                response_body = resp.read()

                start_response(
                    f"{status_code} {status_text}",
                    response_headers,
                )
                return [response_body]

        except urllib.error.HTTPError as e:
            body = e.read()
            response_headers = list(CORS_HEADERS) + [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ]
            start_response(f"{e.code} {e.reason}", response_headers)
            return [body]

        except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
            logging.error(f"MCP proxy: Cannot reach FastMCP server on port 8000: {e}")
            body = b'{"jsonrpc":"2.0","error":{"code":-32000,"message":"MCP server unavailable. It may still be starting up."},"id":null}'
            response_headers = list(CORS_HEADERS) + [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ]
            start_response("502 Bad Gateway", response_headers)
            return [body]

        except Exception as e:
            logging.error(f"MCP proxy error: {e}")
            body = f'{{"jsonrpc":"2.0","error":{{"code":-32000,"message":"Proxy error: {e}"}},"id":null}}'.encode()
            response_headers = list(CORS_HEADERS) + [
                ("Content-Type", "application/json"),
                ("Content-Length", str(len(body))),
            ]
            start_response("500 Internal Server Error", response_headers)
            return [body]
