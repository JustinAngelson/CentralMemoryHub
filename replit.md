# Central Memory Hub (CMH)

## Overview
A multi-agent organizational memory system built with Flask + PostgreSQL + Pinecone. Provides a web UI, REST API for Custom GPTs, and an MCP server for direct Claude.ai / MCP-client integration.

## Architecture

| Component | Port | Protocol | Purpose |
|-----------|------|----------|---------|
| Flask (web UI + REST API) | 5000 | HTTP | Web interface + Custom GPT REST endpoints |
| FastMCP server | 8000 | MCP / Streamable HTTP | Direct MCP protocol access for Claude.ai and agents |
| Flask `/mcp` proxy | 5000 | HTTP → MCP | Public MCP access forwarded to port 8000 |

### API Dual-Endpoint Pattern
- `/api/*` — UI-facing routes, no authentication required
- `/agent/*` — Custom GPT / API routes, require `X-API-KEY` header (case-insensitive)
- `/mcp` — MCP protocol proxy (POST/GET/OPTIONS)

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | Flask app factory, SQLAlchemy setup |
| `main.py` | Gunicorn entry point |
| `models.py` | All 13 SQLAlchemy models |
| `routes.py` | Flask routes (UI + REST API + MCP proxy import) |
| `mcp_server.py` | FastMCP server entry point (30 tools) |
| `mcp_proxy.py` | Flask `/mcp` proxy route to internal FastMCP server |
| `mcp_tools/__init__.py` | Shared DB session + model imports for MCP tools |
| `mcp_tools/memory_tools.py` | 5 tools: search/store/get for unstructured + structured memory |
| `mcp_tools/organization_tools.py` | 10 tools: shared context, org state, decisions, knowledge, memory links |
| `mcp_tools/agent_tools.py` | 15 tools: directory, sessions, messages, tasks, experiments, insights, health |
| `pinecone_client.py` | Pinecone vector embedding client |
| `openapi-schema-fixed.json` | OpenAPI schema for Custom GPT integration |
| `start_all.sh` | Shell script to start both Flask + MCP as separate processes |

## MCP Tools (30 total)

### Memory Tools (5)
- `cmh_search_memory` — Semantic Pinecone search
- `cmh_store_memory` — Store + embed unstructured content
- `cmh_get_memory` — Retrieve by UUID
- `cmh_store_structured` — Store structured memory with role attribution
- `cmh_get_structured` — Retrieve structured memory by UUID

### Organization Tools (10)
- `cmh_share_context` — Broadcast memory refs to agents
- `cmh_list_contexts` — List all shared context entries
- `cmh_create_org_state` — Create entity state snapshot
- `cmh_update_org_state` — Update entity state
- `cmh_list_org_states` — Filter/list org states
- `cmh_log_decision` — Record decision with attribution
- `cmh_list_decisions` — Filter/list decision log
- `cmh_store_knowledge` — Index knowledge term
- `cmh_search_knowledge` — Search knowledge index
- `cmh_create_memory_link` — Link Pinecone vector to metadata
- `cmh_list_memory_links` — Filter/list memory links

### Agent Tools (15)
- `cmh_list_agents` — Hierarchical org chart (reports_to tree)
- `cmh_register_agent` — Add agent to directory
- `cmh_create_session` — Start agent session
- `cmh_end_session` — End session (sets ended_at)
- `cmh_list_sessions` — Filter/list sessions
- `cmh_send_message` — Log inter-agent message
- `cmh_create_task` — Create and assign task
- `cmh_update_task` — Update task status/assignment
- `cmh_list_tasks` — Filter/list tasks
- `cmh_create_experiment` — Track experiment
- `cmh_list_experiments` — Filter/list experiments
- `cmh_log_user_insight` — Record user behavior insight
- `cmh_list_user_insights` — Filter/list user insights
- `cmh_health_check` — DB + Pinecone connectivity check

## Workflows
- **Start application** — `gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app`
- **MCP Server** — `MCP_TRANSPORT=streamable-http MCP_PORT=8000 python mcp_server.py`

## Environment Secrets Required
- `DATABASE_URL` — PostgreSQL connection string
- `OPENAI_API_KEY` — For text-embedding-ada-002 embeddings
- `PINECONE_API_KEY` — For vector storage/search
- `API_KEY` — For Custom GPT authentication (`X-API-KEY` header)
- `SESSION_SECRET` — Flask session secret

## Production URL
`https://memory-vault-angelson.replit.app`
- MCP endpoint: `https://memory-vault-angelson.replit.app/mcp`
