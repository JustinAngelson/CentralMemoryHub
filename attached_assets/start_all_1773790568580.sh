#!/bin/bash
# Start both Flask (CMH web UI + REST API) and MCP server
# For use in Replit or any deployment that needs both services.

echo "=== Central Memory Hub + MCP Server ==="

# Start Flask on port 5000 (existing app)
echo "Starting Flask on :5000..."
gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 120 main:app &
FLASK_PID=$!

# Give Flask a moment to start
sleep 2

# Start MCP server on port 8001
echo "Starting MCP server on :8001..."
MCP_TRANSPORT=streamable_http MCP_PORT=8001 python mcp_server.py &
MCP_PID=$!

echo ""
echo "Flask PID:  $FLASK_PID  →  http://0.0.0.0:5000"
echo "MCP PID:    $MCP_PID  →  http://0.0.0.0:8001/mcp"
echo ""
echo "To connect Claude.ai: add MCP connector pointing to your-domain:8001/mcp"
echo "To connect OpenClaw:  use MCP_TRANSPORT=stdio python mcp_server.py"
echo ""

# If either process exits, bring down the other
trap "kill $FLASK_PID $MCP_PID 2>/dev/null" EXIT

# Wait for either to exit
wait -n $FLASK_PID $MCP_PID
EXIT_CODE=$?

echo "A process exited with code $EXIT_CODE — shutting down..."
kill $FLASK_PID $MCP_PID 2>/dev/null
exit $EXIT_CODE
