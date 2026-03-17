"""
Central Memory Hub MCP Server

Exposes CMH organizational memory through the Model Context Protocol,
enabling Claude.ai, Nix, Jr, TT, and any MCP client to search, store,
and manage shared organizational memory.

Run standalone:   python mcp_server.py
Stdio mode:       MCP_TRANSPORT=stdio python mcp_server.py
HTTP mode:        MCP_TRANSPORT=streamable_http MCP_PORT=8001 python mcp_server.py
"""
import os
import logging
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)

# Initialize FastMCP server
mcp = FastMCP("cmh_mcp")

# Import and register all tool modules
from mcp_tools.memory_tools import register_memory_tools
from mcp_tools.organization_tools import register_organization_tools
from mcp_tools.agent_tools import register_agent_tools

register_memory_tools(mcp)
register_organization_tools(mcp)
register_agent_tools(mcp)

logging.info("CMH MCP Server initialized with all tool modules.")

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "streamable_http")
    port = int(os.environ.get("MCP_PORT", "8001"))

    logging.info(f"Starting CMH MCP Server (transport={transport}, port={port})")

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable_http", port=port)
