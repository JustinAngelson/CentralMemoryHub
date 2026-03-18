#!/bin/bash
# Start both the MCP server (background) and Flask (foreground).
# Flask on port 5000 is the health-check target.
# MCP server on port 8000 is accessed internally via the /mcp proxy.

echo "=== Central Memory Hub ==="

# Kill any leftover processes from a previous run
echo "Clearing previous processes..."
pkill -f "mcp_server.py" 2>/dev/null || true
pkill -f "gunicorn" 2>/dev/null || true
sleep 2

# Start MCP server in the background first
echo "Starting MCP server on :8000..."
MCP_TRANSPORT=streamable-http MCP_PORT=8000 python mcp_server.py &
MCP_PID=$!

echo "MCP PID: $MCP_PID"

# Kill MCP server when this script exits for any reason
trap "kill $MCP_PID 2>/dev/null" TERM INT EXIT

# Run Flask via gunicorn in the foreground (this is what deployment waits for on :5000)
echo "Starting Flask on :5000..."
exec gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 120 main:app
