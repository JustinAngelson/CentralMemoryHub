# Implementation Brief: Add MCP Server to Central Memory Hub

## Objective

Add a Model Context Protocol (MCP) server to the existing Central Memory Hub Flask application. This gives Claude.ai, Nix, Jr, TT, and any MCP-compatible client direct access to the CMH's organizational memory through a standardized protocol.

## Architecture Decision

The MCP server will be implemented in Python using FastMCP and integrated into the existing CMH project. The MCP tools will access the database **directly through SQLAlchemy** (the same `db` instance and models already used by the Flask routes), NOT by making HTTP calls to the Flask API. This eliminates internal network overhead and API key requirements for self-calls.

Flask (WSGI) and FastMCP Streamable HTTP (ASGI) cannot share the same port. The solution is to run them as two processes in the same Replit project:

- **Flask** continues on port 5000 (the existing web UI + REST API)
- **FastMCP** runs on port 8001 (MCP protocol endpoint at `/mcp`)

Both processes share the same codebase, models, and database connection.

---

## Step 1: Install Dependencies

Add to `requirements.txt` (or `pyproject.toml`):

```
mcp[cli]>=1.0.0
```

The `mcp` package includes FastMCP. All other dependencies (Flask, SQLAlchemy, etc.) are already present.

---

## Step 2: Create File Structure

Add these files to the existing project:

```
(existing CMH project root)
├── mcp_server.py              # FastMCP server with all 30 tools
├── mcp_tools/                 # Tool modules (one per domain)
│   ├── __init__.py
│   ├── memory_tools.py        # 5 tools: search, store, get
│   ├── organization_tools.py  # 10 tools: context, org state, decisions, knowledge, links
│   └── agent_tools.py         # 15 tools: directory, sessions, messages, tasks, experiments, insights, health
├── start_all.sh               # Startup script for both Flask + MCP
└── (existing files unchanged)
```

---

## Step 3: Startup Configuration

### start_all.sh

```bash
#!/bin/bash
# Start both Flask and MCP servers
echo "Starting Central Memory Hub..."

# Start Flask (existing app) on port 5000
gunicorn --bind 0.0.0.0:5000 --workers 2 main:app &
FLASK_PID=$!

# Start MCP server on port 8001
python mcp_server.py &
MCP_PID=$!

echo "Flask running on :5000 (PID: $FLASK_PID)"
echo "MCP server running on :8001 (PID: $MCP_PID)"

# Wait for either to exit
wait -n $FLASK_PID $MCP_PID
```

### Replit Configuration

In `.replit`, update the run command:

```toml
run = "bash start_all.sh"
```

Or if using Replit's Nix/workflow config, ensure both processes start.

If Replit only exposes one port publicly, use port 5000 for Flask and add a reverse proxy route in Flask to forward `/mcp` requests to the FastMCP process on 8001. Alternatively, configure Replit to expose port 8001 as a second public endpoint.

---

## Step 4: Implement mcp_server.py (Main Entry Point)

```python
"""
Central Memory Hub MCP Server

Exposes CMH organizational memory through the Model Context Protocol,
enabling Claude.ai, Nix, Jr, TT, and any MCP client to search, store,
and manage shared organizational memory.

Run: python mcp_server.py
"""
import os
import logging
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP
mcp = FastMCP("cmh_mcp")

# Import and register all tool modules
# (each module registers tools via the @mcp.tool decorator)
from mcp_tools.memory_tools import register_memory_tools
from mcp_tools.organization_tools import register_organization_tools
from mcp_tools.agent_tools import register_agent_tools

# Register all tools with the MCP server instance
register_memory_tools(mcp)
register_organization_tools(mcp)
register_agent_tools(mcp)

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "streamable_http")
    port = int(os.environ.get("MCP_PORT", "8001"))

    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable_http", port=port)
```

---

## Step 5: Implement Database Access Helper

Each tool module needs access to the Flask app's database. Create a shared helper in `mcp_tools/__init__.py`:

```python
"""
Shared database access for MCP tools.

Uses the same SQLAlchemy session and models as the Flask app.
This avoids HTTP self-calls and API key overhead.
"""
import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

# Use the same DATABASE_URL as Flask
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    engine = create_engine(DATABASE_URL)
    SessionLocal = scoped_session(sessionmaker(bind=engine))
else:
    engine = None
    SessionLocal = None
    logging.warning("DATABASE_URL not set — MCP tools will not have DB access")


def get_db_session():
    """Get a database session. Caller must close it."""
    if SessionLocal is None:
        raise RuntimeError("Database not configured. Set DATABASE_URL.")
    return SessionLocal()


# Import models from the existing app
# These are the same SQLAlchemy models used by routes.py
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    ProjectDecision, UnstructuredData, SharedContext,
    AgentDirectory, AgentSession, GPTMessage, OrgState,
    AgentTask, DecisionLog, KnowledgeIndex, MemoryLink,
    Experiment, UserInsight
)

# Pinecone client for vector operations
try:
    import pinecone_client as pc
    PINECONE_AVAILABLE = True
except ImportError:
    pc = None
    PINECONE_AVAILABLE = False
    logging.warning("pinecone_client not importable — vector search unavailable")
```

**IMPORTANT**: The exact import path for models may need adjustment based on the project structure. The goal is to reuse the existing `models.py` and `pinecone_client.py` directly.

---

## Step 6: Tool Specifications

Below are all 30 tools organized by module. Each entry includes the tool name, description (for the docstring), input parameters (for Pydantic models), annotations, and implementation notes.

### 6A. Memory Tools (mcp_tools/memory_tools.py) — 5 tools

---

#### cmh_search_memory
- **Purpose**: Semantic search across unstructured memories via Pinecone
- **Annotations**: readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
- **Inputs**:
  - `query` (str, required, min_length=1, max_length=1000): Natural-language search query
- **Implementation**: Call `pc.search_by_content(query)` to get Pinecone results, then query `UnstructuredData` by matching `pinecone_id` values. Return results sorted by similarity score.
- **Returns**: Formatted text with ranked results showing score, ID, and content.

#### cmh_store_memory
- **Purpose**: Store unstructured content with automatic Pinecone embedding
- **Annotations**: readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
- **Inputs**:
  - `content` (str, required, min_length=1, max_length=10000): Content to store
- **Implementation**: Call `pc.process_unstructured_data(content)` to get embedding + pinecone_id, create `UnstructuredData` record, commit to DB.
- **Returns**: Confirmation with DB ID and Pinecone ID.
- **Docstring should include best practices**: Include provenance tags [source: direct|reconstructed|consolidated|reported|inferred], type tags [type: state|episode|pattern|fact|relationship], and agent tags [agent: nix|claude|jr|tt|justin].

#### cmh_get_memory
- **Purpose**: Retrieve a specific unstructured memory by UUID
- **Annotations**: readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
- **Inputs**:
  - `id` (str, required): UUID of the memory
- **Implementation**: `UnstructuredData.query.get(id)`

#### cmh_store_structured
- **Purpose**: Store structured memory with role attribution and document links
- **Annotations**: readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
- **Inputs**:
  - `gpt_role` (str, required): Role of the storing agent
  - `decision_text` (str, required): Decision/information content
  - `context_embedding` (List[float], required): Pre-computed vector embedding
  - `related_documents` (List[str], required): Related document IDs
- **Implementation**: Create `ProjectDecision` record, commit to DB.

#### cmh_get_structured
- **Purpose**: Retrieve structured memory by UUID
- **Annotations**: readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
- **Inputs**:
  - `id` (str, required): UUID of the structured memory

---

### 6B. Organization Tools (mcp_tools/organization_tools.py) — 10 tools

---

#### cmh_share_context
- **Purpose**: Create a cross-agent context entry linking agents to tagged memory refs
- **Annotations**: readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
- **Inputs**:
  - `sender` (str, required): Sending agent identifier
  - `recipients` (List[str], required, min_items=1): Target agents
  - `context_tag` (str, required, max_length=100): Descriptive tag
  - `memory_refs` (List[str], required, min_items=1): Memory IDs to reference
- **Implementation**: Create `SharedContext` record.

#### cmh_list_contexts
- **Purpose**: Retrieve all shared context entries
- **Annotations**: readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
- **Inputs**: None
- **Implementation**: `SharedContext.query.all()`

#### cmh_create_org_state
- **Purpose**: Track state of a project, client, or entity
- **Annotations**: readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
- **Inputs**:
  - `entity` (str, required): Entity name
  - `type` (str, required): Entity type (client, project, infrastructure, process)
  - `status` (str, required): Current status
  - `owner_agent` (str, required): Primary responsible agent
  - `last_updated_by` (str, required): Who is making this update
  - `summary` (str, optional): Brief description
  - `important_dates` (Dict[str, str], optional): Key dates
  - `linked_docs` (List[str], optional): Document references
- **Implementation**: Create `OrgState` record.

#### cmh_update_org_state
- **Purpose**: Update an existing org state entry
- **Annotations**: readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
- **Inputs**:
  - `entity_id` (str, required): Entity ID
  - `status` (str, optional), `summary` (str, optional), `owner_agent` (str, optional), `last_updated_by` (str, required), `important_dates` (Dict, optional), `linked_docs` (List[str], optional)

#### cmh_list_org_states
- **Purpose**: List org states with optional filters
- **Annotations**: readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
- **Inputs**: `type` (str, optional), `status` (str, optional), `owner_agent` (str, optional)

#### cmh_log_decision
- **Purpose**: Record a decision with context and attribution
- **Annotations**: readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
- **Inputs**:
  - `context` (str, required): Situation context
  - `made_by_agent` (str, required): Decision maker
  - `decision_text` (str, required): The decision
  - `impact_area` (str, optional): Affected area
  - `reversal_possible` (bool, optional, default=True): Reversible?

#### cmh_list_decisions
- **Purpose**: List decision log with filters
- **Annotations**: readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
- **Inputs**: `made_by_agent`, `impact_area`, `reversal_possible` (str "true"/"false"), `from_date`, `to_date` (ISO strings) — all optional

#### cmh_store_knowledge
- **Purpose**: Index a knowledge term with provenance and usage tracking
- **Annotations**: readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
- **Inputs**:
  - `term` (str, required): The knowledge term
  - `defined_by_file` (str, optional), `used_by_agents` (List[str], optional), `relevance_score` (int 1-10, optional), `synonyms` (List[str], optional)

#### cmh_search_knowledge
- **Purpose**: Search knowledge index
- **Annotations**: readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
- **Inputs**: `term` (str, optional, partial match), `agent` (str, optional), `min_relevance` (int 1-10, optional)

#### cmh_create_memory_link
- **Purpose**: Link a Pinecone vector to metadata
- **Annotations**: readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
- **Inputs**: `pinecone_vector_id` (str, required), `summary` (str, optional), `linked_agent_event` (str, optional), `origin_file_or_source` (str, optional)

#### cmh_list_memory_links
- **Purpose**: List memory links with filters
- **Annotations**: readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
- **Inputs**: `pinecone_vector_id`, `linked_agent_event`, `origin_file_or_source` — all optional

---

### 6C. Agent Tools (mcp_tools/agent_tools.py) — 15 tools

---

#### cmh_list_agents
- **Purpose**: Get hierarchical agent directory (org chart)
- **Annotations**: readOnlyHint=True
- **Inputs**: None
- **Implementation**: Query `AgentDirectory`, build hierarchy tree from `reports_to` relationships. Use the same `build_hierarchy_tree()` logic from routes.py.

#### cmh_register_agent
- **Purpose**: Add agent to directory
- **Inputs**: `name` (str, required, unique), `role` (str, required), `description` (optional), `capabilities` (List[str], optional), `reports_to` (str, optional), `seniority_level` (int 1-10, optional), `status` (enum: active/inactive/archived, optional, default active)

#### cmh_create_session
- **Purpose**: Start agent session
- **Inputs**: `agent_id` (str, required), `user_id` (optional), `current_focus` (optional), `summary_notes` (optional), `active_context_tags` (List[str], optional)

#### cmh_end_session
- **Purpose**: End session by setting ended_at timestamp
- **Inputs**: `session_id` (str, required)

#### cmh_list_sessions
- **Purpose**: List sessions with filters
- **Inputs**: `agent_id`, `user_id` (optional), `active_only` (bool, optional, default False)

#### cmh_send_message
- **Purpose**: Log inter-agent message within a session
- **Inputs**: `sender_agent` (str, required), `session_id` (str, required), `content` (str, required), `message_type` (enum: system/user/assistant/function/tool/data, required), `receiver_agent` (str, optional)

#### cmh_create_task
- **Purpose**: Create and assign agent task
- **Inputs**: `title` (str, required), `assigned_to_agent` (str, required), `created_by_agent` (str, required), `status` (enum: pending/in_progress/completed/cancelled/blocked, required), `description` (optional), `priority` (enum: low/medium/high/critical, optional), `linked_project` (optional), `summary_notes` (optional), `due_date` (ISO string, optional)

#### cmh_update_task
- **Purpose**: Update task status/assignment/details
- **Inputs**: `task_id` (str, required), then optional: `status`, `title`, `assigned_to_agent`, `priority`, `summary_notes`

#### cmh_list_tasks
- **Purpose**: List tasks with filters
- **Inputs**: `assigned_to_agent`, `created_by_agent`, `status`, `linked_project` — all optional

#### cmh_create_experiment
- **Purpose**: Track agent experiment
- **Inputs**: `title` (required), `hypothesis` (required), `executing_agent` (required), `status` (required), `description` (optional), `outcome` (optional), `notes` (optional)

#### cmh_list_experiments
- **Purpose**: List experiments with filters
- **Inputs**: `status` (optional), `executing_agent` (optional)

#### cmh_log_user_insight
- **Purpose**: Record user behavior insight
- **Inputs**: `user_id` (required), `interaction_type` (required), `summary` (required), `related_agent_or_project` (optional), `result` (optional), `tone_tag` (optional)

#### cmh_list_user_insights
- **Purpose**: List insights with filters
- **Inputs**: `user_id`, `interaction_type`, `tone_tag`, `from_date`, `to_date` — all optional

#### cmh_health_check
- **Purpose**: Check CMH database and Pinecone connectivity
- **Annotations**: readOnlyHint=True, openWorldHint=True
- **Inputs**: None
- **Implementation**: Test DB connection with a simple query, test Pinecone with `pc.get_index_stats()`. Return status object.

---

## Step 7: Testing

After implementation, verify:

1. **Flask still works**: `curl https://your-replit-url.replit.app/sys/health`
2. **MCP server responds**: `curl https://your-replit-url.replit.app:8001/mcp` (or proxied path)
3. **MCP initialize handshake**: Send JSON-RPC initialize request, confirm capabilities include tools
4. **tools/list**: Confirm all 30 tools appear
5. **tools/call**: Test `cmh_health_check`, then `cmh_search_memory` with a known query, then `cmh_store_memory` with a test entry

---

## Step 8: Port Exposure / Reverse Proxy

If Replit only exposes one port publicly, add a Flask route that proxies MCP requests:

```python
# In routes.py or a new mcp_proxy.py
import requests

@app.route('/mcp', methods=['POST'])
def mcp_proxy():
    """Proxy MCP requests to the FastMCP server on port 8001."""
    resp = requests.post(
        'http://localhost:8001/mcp',
        json=request.json,
        headers={
            'Content-Type': 'application/json',
            'Accept': request.headers.get('Accept', 'application/json')
        }
    )
    return resp.content, resp.status_code, dict(resp.headers)
```

This way Claude.ai connects to `https://memory-vault-angelson.replit.app/mcp` and the request is forwarded internally.

---

## Summary

| Component | Port | Protocol | Purpose |
|-----------|------|----------|---------|
| Flask (existing) | 5000 | HTTP/REST | Web UI + REST API for GPTs |
| FastMCP (new) | 8001 | MCP/Streamable HTTP | MCP protocol for Claude.ai and agents |
| Flask /mcp proxy | 5000 | HTTP → MCP | Public MCP access through existing port |

**Total new tools**: 30
**New dependencies**: `mcp[cli]`
**Existing code changes**: Minimal — just the proxy route and startup script
**Database changes**: None — uses existing models and schema
