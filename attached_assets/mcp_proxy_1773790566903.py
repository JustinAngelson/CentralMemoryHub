"""
MCP Proxy Route for Flask

Adds a /mcp endpoint to the Flask app that proxies requests to the
FastMCP server running on port 8001. This solves the single-port
exposure problem on Replit — Claude.ai can connect to the same public
URL at /mcp and requests are forwarded internally.

Usage: Import this module in main.py or routes.py:
    import mcp_proxy  # registers the /mcp route on the Flask app

Requires: requests (already in CMH dependencies)
"""
import logging
import requests as http_requests
from flask import request, make_response
from app import app

MCP_INTERNAL_URL = "http://localhost:8001/mcp"


@app.route('/mcp', methods=['POST', 'OPTIONS'])
def mcp_proxy():
    """Proxy MCP protocol requests to the internal FastMCP server."""
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = make_response('', 204)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Accept'
        return response

    try:
        # Forward the request to FastMCP
        resp = http_requests.post(
            MCP_INTERNAL_URL,
            json=request.json,
            headers={
                'Content-Type': 'application/json',
                'Accept': request.headers.get('Accept', 'application/json, text/event-stream'),
            },
            timeout=30,
        )

        # Build Flask response from upstream
        response = make_response(resp.content, resp.status_code)
        response.headers['Content-Type'] = resp.headers.get('Content-Type', 'application/json')
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    except http_requests.ConnectionError:
        logging.error("MCP proxy: Cannot reach FastMCP server on port 8001")
        return {
            "jsonrpc": "2.0",
            "error": {
                "code": -32000,
                "message": "MCP server is not running. Check that mcp_server.py is started on port 8001."
            },
            "id": None
        }, 502
    except Exception as e:
        logging.error(f"MCP proxy error: {e}")
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32000, "message": f"Proxy error: {str(e)}"},
            "id": None
        }, 500
