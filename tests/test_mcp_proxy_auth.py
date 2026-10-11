import ast
import io
import os
from pathlib import Path
import tomllib
import unittest
from unittest.mock import MagicMock, patch

from mcp_proxy import MCPProxyMiddleware


class MCPProxyAuthTests(unittest.TestCase):
    def setUp(self):
        self.fallback = MagicMock(return_value=[b"ordinary route"])
        self.proxy = MCPProxyMiddleware(self.fallback)

    def request(self, path="/mcp", method="POST", authorization=None, **extra):
        environ = {
            "PATH_INFO": path,
            "REQUEST_METHOD": method,
            "CONTENT_LENGTH": "0",
            "wsgi.input": io.BytesIO(),
            **extra,
        }
        if authorization is not None:
            environ["HTTP_AUTHORIZATION"] = authorization
        response = {}

        def start_response(status, headers):
            response.update(status=status, headers=dict(headers))

        response["body"] = b"".join(self.proxy(environ, start_response))
        return response

    @patch.dict(os.environ, {"MCP_BEARER_TOKEN": "test-only-token"}, clear=True)
    @patch("mcp_proxy.urllib.request.urlopen")
    def test_unauthorized_requests_never_reach_upstream(self, upstream):
        for path in ("/mcp", "/mcp/"):
            for method in ("GET", "POST", "DELETE", "PUT", "HEAD"):
                for header in (None, "", "Bearer", "Basic test-only-token",
                               "Bearer wrong", "Bearer test-only-token extra",
                               "Bearer \u2603"):
                    with self.subTest(path=path, method=method, header=header):
                        result = self.request(path, method, header)
                        self.assertEqual(result["status"], "401 Unauthorized")
                        self.assertIn("WWW-Authenticate", result["headers"])
        upstream.assert_not_called()
        self.fallback.assert_not_called()

    @patch.dict(os.environ, {"MCP_BEARER_TOKEN": "test-only-token"}, clear=True)
    @patch("mcp_proxy.urllib.request.urlopen")
    def test_unknown_subpaths_do_not_exist(self, upstream):
        for path in ("/mcp/unsupported", "/mcp/unsupported/nested"):
            for method in ("GET", "POST", "OPTIONS", "DELETE"):
                for authorization in (None, "Bearer test-only-token"):
                    result = self.request(path, method, authorization)
                    self.assertEqual(result["status"], "404 Not Found")
                    self.assertNotIn("WWW-Authenticate", result["headers"])
        upstream.assert_not_called()
        self.fallback.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch("mcp_proxy.urllib.request.urlopen")
    def test_missing_configuration_fails_closed(self, upstream):
        result = self.request(authorization="Bearer anything")
        self.assertEqual(result["status"], "503 Service Unavailable")
        upstream.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch("mcp_proxy.urllib.request.urlopen")
    def test_no_token_is_401_even_without_configuration(self, upstream):
        for path in ("/mcp", "/mcp/"):
            for header in (None, "", "Bearer", "Basic anything"):
                result = self.request(path=path, authorization=header)
                self.assertEqual(result["status"], "401 Unauthorized")
                self.assertIn("WWW-Authenticate", result["headers"])
        upstream.assert_not_called()

    @patch.dict(os.environ, {"MCP_BEARER_TOKEN": "test-only-token"}, clear=True)
    @patch("mcp_proxy.urllib.request.urlopen")
    def test_valid_token_proxies_without_leaking_credential(self, upstream):
        response = upstream.return_value.__enter__.return_value
        response.status, response.reason = 200, "OK"
        response.headers.items.return_value = [("content-type", "application/json")]
        response.read.return_value = b'{"jsonrpc":"2.0","id":1}'
        result = self.request(
            authorization="bEaReR test-only-token", HTTP_MCP_SESSION_ID="test-session"
        )
        self.assertEqual(result["status"], "200 OK")
        self.assertEqual(result["body"], b'{"jsonrpc":"2.0","id":1}')
        request = upstream.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8000/mcp")
        self.assertEqual(request.get_header("Mcp-session-id"), "test-session")
        self.assertIsNone(request.get_header("Authorization"))

    @patch.dict(os.environ, {"MCP_BEARER_TOKEN": "test-only-token"}, clear=True)
    @patch("mcp_proxy.urllib.request.urlopen")
    def test_other_credentials_cannot_bypass_auth(self, upstream):
        result = self.request(
            HTTP_X_API_KEY="test-only-token",
            HTTP_MCP_SESSION_ID="existing-session",
            HTTP_COOKIE="session=existing-login",
            QUERY_STRING="token=test-only-token",
        )
        self.assertEqual(result["status"], "401 Unauthorized")
        upstream.assert_not_called()

    @patch("mcp_proxy.urllib.request.urlopen")
    def test_preflight_does_not_reach_upstream(self, upstream):
        result = self.request(method="OPTIONS")
        self.assertEqual(result["status"], "204 No Content")
        self.assertIn("Authorization", result["headers"]["Access-Control-Allow-Headers"])
        upstream.assert_not_called()

    def test_non_mcp_routes_are_unchanged(self):
        result = self.request(path="/landing", method="GET")
        self.assertEqual(result["body"], b"ordinary route")
        self.fallback.assert_called_once()

    def test_fastmcp_is_loopback_only(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "mcp_server.py").read_text())
        server = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "FastMCP"
        )
        host = next(keyword.value for keyword in server.keywords if keyword.arg == "host")
        self.assertEqual(ast.literal_eval(host), "127.0.0.1")

    def test_internal_port_is_not_exposed(self):
        root = Path(__file__).resolve().parents[1]
        config = tomllib.loads((root / ".replit").read_text())
        self.assertFalse(any(port["localPort"] == 8000 for port in config.get("ports", [])))


if __name__ == "__main__":
    unittest.main()
