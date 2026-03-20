# Central Memory Hub (CMH)
### Draft Overview — For Partner Review

---

## What Is CMH?

The Central Memory Hub is a persistent, shared memory and operations platform built for teams that work with AI agents. It gives every agent, Custom GPT, and human collaborator a single place to store what they know, track what they decide, and coordinate what they do — across sessions, across tools, and across time.

Rather than each AI agent starting from scratch in every conversation, CMH acts as the organizational brain: a live, searchable knowledge base that agents and humans both contribute to and draw from.

The platform is live and production-deployed at:
**https://memory-vault-angelson.replit.app**

---

## Core Technology

| Layer | Technology |
|---|---|
| Web application | Python / Flask |
| Relational database | PostgreSQL (structured records, org data) |
| Vector database | Pinecone (semantic / AI search) |
| Embeddings | OpenAI text-embedding-ada-002 |
| Hosting | Replit Reserved VM (always-on) |

---

## What The Platform Does

CMH is organized around five functional areas, each accessible through the web UI and through the API.

### 1. Memory — Store and Search Anything

Every piece of information that agents or users want to keep is stored as a memory. CMH supports two types:

- **Unstructured memories** — free-form text, notes, observations, or any natural language content. These are embedded with OpenAI and stored in Pinecone, enabling true semantic search ("find everything related to onboarding delays" returns relevant results even if those exact words never appeared).
- **Structured memories** — formal records with roles, decision text, and vector context, for decisions that need to be auditable and traceable.

Memories can be linked to each other (MemoryLinks), giving agents the ability to navigate related information the way a human would follow a thread of thought.

### 2. Agent Directory — AI Org Chart

CMH maintains a live registry of every AI agent in the organization. Think of it as an org chart, but for your AI team:

- Each agent has a **name, role, description, seniority level, and status** (active, in training, inactive)
- Agents can **report to other agents**, creating a hierarchy with full tree visualization
- Each agent profile tracks its **usual model** (Claude, GPT-4o, LLaMA, etc.), **capabilities** (JSON array), and **skills** (linked to the Skill Registry)
- **Agent sessions** capture what each agent is working on and when, with session start/end timestamps and current focus tracking
- **Inter-agent messages** are logged by type: instruction, status update, handoff, or question

The hierarchy view lets you see at a glance how your AI team is structured and who reports to whom.

### 3. Skill Registry — What Your Team Knows

A centralized registry of skills available across the organization — both human and AI. Each skill record includes:

- **Type** — Agent, Human, or Hybrid
- **Point of Contact** — who or what handles this skill (Any, Agents, or Users)
- **Source** — where the skill comes from (URL, course, tool, internal document)
- **Description** — full narrative
- **Attached files** — up to 5 supporting documents per skill (Markdown, PDF, DOCX, TXT) for capability documentation like Skills.md files

Skills connect to the rest of the system: agents can be linked to the skills they hold, and users can tag their own profiles with skills from the registry.

### 4. Resource Directory — Tools, Assets, and Integrations

A catalog of every resource the organization operates with:

- **Types:** Tool, Asset, Integration, Service, Document, or Other
- **Point of Contact:** who owns or manages each resource
- **Access & URLs** — direct links to tools and systems
- **Related skills** — what capabilities are needed to use each resource
- Fields for licensing, cost, environment (production/staging/dev), visibility (internal/external), and status (active/deprecated/planned)
- An optional **POC badge** prominently flags which resources are agent-operated vs. human-managed

### 5. Knowledge Index & Decisions — The Audit Trail

Beyond memories, CMH tracks the *reasoning* behind decisions:

- **Decision Log** — every significant agent decision is logged with context, impact area, and whether it is reversible. This creates a full audit trail of how your AI team operates.
- **Knowledge Index** — a glossary of domain terms with definitions, sources, synonyms, and relevance scoring. Agents use this to resolve ambiguity and stay consistent in language.
- **Org State** — snapshots of organizational entities (projects, clients, processes) so agents know current status without having to ask
- **Agent Tasks** — structured task assignments with priority, status, due dates, and instructions
- **Experiments** — hypothesis tracking for testing agent strategies, with outcome recording
- **User Insights** — behavioral and interaction pattern logging for learning and improvement over time

---

## How Agents and Tools Connect to CMH

CMH is designed to be used three ways simultaneously.

### A. Web UI (Human-Facing)
A full browser interface with role-based access (admin and standard user roles). Humans can browse memories, manage the agent directory, update skills and resources, administer users, view API keys, and configure org settings.

Admin-only features include: user management, invitation system, API key creation/revocation, rate limit configuration, and org profile settings.

### B. REST API (Custom GPTs and External Integrations)
Every feature is accessible via a RESTful API secured with API key authentication (X-API-KEY header). This is how Custom GPTs connect to CMH:

- A Custom GPT stores a memory: `POST /memory/unstructured`
- It searches past context: `POST /search`
- It logs a decision: `POST /agent/decision-log`
- It registers itself: `POST /agent/directory`
- It creates a task: `POST /agent/tasks`

The full OpenAPI schema is available at `/openapi.json` and served directly from the running application.

Each API key can be scoped with custom rate limits and has a full request log — every API call is audited with timestamp, IP address, endpoint, and response status.

### C. MCP Server (Claude Desktop and AI Agents)
CMH runs a full **Model Context Protocol (MCP) server** on a dedicated port, using the streamable-HTTP transport. This means Claude Desktop, Claude.ai Projects, and any MCP-compatible AI agent can connect to CMH as a native tool without any custom integration code.

The MCP server exposes named tools that agents call directly:

| Tool | What it does |
|---|---|
| `cmh_search_memory` | Semantic search across all stored memories |
| `cmh_store_memory` | Save new unstructured memory with auto-embedding |
| `cmh_get_memory` | Retrieve a specific memory by ID |
| `cmh_store_structured` | Save a formal structured decision record |
| `cmh_share_context` | Broadcast context from one agent to others |
| `cmh_log_decision` | Add an entry to the decision audit log |
| `cmh_store_knowledge` | Add a term to the knowledge index |
| `cmh_create_memory_link` | Link two memory records together |
| `cmh_list_agents` | Get the full agent roster and org hierarchy |
| `cmh_register_agent` | Add a new agent to the directory |
| `cmh_create_session` | Start an agent work session |
| `cmh_send_message` | Log an inter-agent message |
| `cmh_create_task` | Create a task assignment |
| `cmh_create_org_state` | Record an organizational entity snapshot |

---

## Security Model

- **Dual authentication** — browser sessions use secure cookies (Flask-Login); API consumers use API keys via X-API-KEY header
- **Role-based access** — admin vs. standard user controls access to sensitive management pages
- **API key management** — keys can be created, revoked, and rate-limited per key; all requests are logged
- **Input validation** — schema-based validation on all API endpoints with type checking and constraint enforcement
- **CSRF protection** — all form submissions are protected against cross-site request forgery
- **Content Security Policy** — strict CSP headers prevent script injection
- **Invitation-only registration** — new users can only join via admin-generated invitation tokens

---

## User Management

- Admin users can invite new members via time-limited invitation tokens (email or link-based)
- Each user has a full profile: name, contact details (phone, WhatsApp, Signal, Telegram), company, website, and profile photo
- Users link their personal skill profile to the Skill Registry
- Password change with confirmation is available from the profile page

---

## Current Status

The platform is fully operational in production. All five core modules (Memory, Agents, Skills, Resources, Knowledge) are live and functional, with the web UI, REST API, and MCP server all running simultaneously on a single always-on deployment.

**Production URL:** https://memory-vault-angelson.replit.app
**API documentation:** https://memory-vault-angelson.replit.app/api-docs
**OpenAPI schema:** https://memory-vault-angelson.replit.app/openapi.json
**MCP server endpoint:** https://memory-vault-angelson.replit.app/mcp

---

*This document is a working draft for partner review. Technical integration details, API key provisioning, and onboarding materials available on request.*
