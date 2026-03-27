# Central Memory Hub

**Vendor-neutral organizational memory for multi-agent AI systems.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![SOMI](https://img.shields.io/badge/category-SOMI-purple)](https://CentralMemoryHub.com)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-green)](https://modelcontextprotocol.io)

---

![CMH Architecture](docs/CMH%20Architecture%20Map%20v1.2.png)

## The Problem

Agents forget each other.

Each AI model has its own context window, its own session, its own memory tooling. The moment you coordinate across models — or across sessions, tools, or time — you're flying blind. No shared decisions. No shared knowledge. No organizational continuity. Every agent starts from scratch.

This gets more acute, not less, as multi-agent systems mature. A single capable agent with no memory is a useful tool. A network of capable agents with no *shared* memory is chaos with good intentions.

CMH is the persistence layer that fills that gap.

---

## The Category

Researchers have begun calling this space **SOMI — Shared Organizational Memory Infrastructure**. Independent analysis mapped the landscape: **$5.9B TAM by 2027**, a well-funded competitive field (Mem0, Letta, Zep), and one notable gap — no vendor-neutral, model-agnostic implementation that any agent on any platform can use without lock-in.

CMH is a working implementation of exactly that gap.

No vendor lock-in. Any model. One memory.

---

## What CMH Does

CMH is organized around five functional areas, accessible through a web UI, a REST API, and a full MCP server simultaneously.

### 1. Memory — Store and Search Anything
- **Unstructured memories** — free-form text, notes, observations. Embedded with OpenAI and stored in Pinecone, enabling true semantic search. "Find everything related to onboarding delays" returns relevant results even if those exact words never appeared.
- **Structured memories** — formal records with role attribution, decision text, and vector context. Auditable and traceable.
- **Memory links** — connect related memories so agents can follow threads of thought across sessions and sources.

### 2. Agent Directory — AI Org Chart
A live registry of every AI agent in the organization:
- Name, role, description, seniority level, status (active / in training / inactive)
- Reporting hierarchy with full tree visualization — see how your AI team is structured at a glance
- Capability and skill tracking per agent
- **Inter-agent messaging** — typed messages between agents across sessions and models (instruction, status update, handoff, question)
- Session tracking — what each agent is working on, when sessions start and end

### 3. Skill Registry — What Your Network Knows
A centralized registry of skills available across the organization — agent, human, and hybrid:
- Skill type, point of contact, source, and full description
- Up to 5 attached documents per skill (Markdown, PDF, DOCX, TXT)
- Linked to agents and users — everyone's capabilities are visible to the network

### 4. Resource Directory — Tools, Assets, Integrations
A catalog of every resource the organization operates with:
- Type classification: Tool, Asset, Integration, Service, Document, Other
- Access URLs, licensing, cost, environment (production/staging/dev), visibility, status
- POC badge flagging which resources are agent-operated vs. human-managed

### 5. Knowledge, Decisions & Org State — The Audit Trail
- **Decision log** — every significant decision logged with context, attribution, impact area, and reversibility. Full audit trail of how your AI team operates.
- **Knowledge index** — domain glossary with definitions, sources, synonyms, and relevance scoring. Agents use this to resolve ambiguity and stay consistent in language.
- **Org state** — snapshots of organizational entities (projects, clients, processes) so agents know current status without asking.
- **Agent tasks** — structured assignments with priority, status, due dates, and instructions.
- **Experiments** — hypothesis tracking for testing agent strategies, with outcome recording.
- **User insights** — behavioral and interaction pattern logging for learning and improvement.

---

## Architecture

```
┌────────────────────────────────────────────────────┐
│                  Central Memory Hub                 │
│                                                     │
│   Flask REST API (:5000)    FastMCP Server (:8000)  │
│   /agent/* endpoints        MCP tools               │
│   /api/* (web UI)           memory + org + agent    │
│                                                     │
│   PostgreSQL (structured)   Pinecone (vectors)      │
└────────────────────────────────────────────────────┘
          ↑                             ↑
   Custom GPTs               Claude.ai / MCP clients
   OpenClaw agents           Cursor, Claude Code
   REST API consumers        Any MCP-compatible agent
```

Two integration paths — both reading from and writing to the same underlying database:
- **REST API** (`/agent/*` endpoints) — for Custom GPTs, OpenClaw agents, and any HTTP client
- **MCP server** (`/mcp`) — for Claude.ai, Claude Code, Cursor, and any MCP-compatible client

An agent using the MCP server and an agent using the REST API share the same memory.

---

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL database
- OpenAI API key (embeddings)
- Pinecone API key (vector storage)

### Setup

```bash
git clone https://github.com/JustinAngelson/Central_Memory_Hub.git
cd Central_Memory_Hub

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your credentials

# Start both servers
bash start_all.sh

# Or separately:
gunicorn --bind 0.0.0.0:5000 --reload main:app
MCP_TRANSPORT=streamable-http MCP_PORT=8000 python mcp_server.py
```

### First-run setup
On first launch, visit `https://your-instance-url/setup` to create your admin account. Setup locks after the first admin is created — subsequent users join via invitation tokens only.

### Connect from Claude.ai
1. Claude.ai → Settings → Integrations → Add MCP Server
2. URL: `https://your-instance-url/mcp`
3. All CMH tools are now available in your Claude sessions

### Connect from OpenClaw
```json
{
  "cmh": {
    "url": "https://your-instance-url/mcp",
    "transport": "streamable-http"
  }
}
```

### Connect a Custom GPT
Use the REST API with your API key in the `X-API-KEY` header. The full OpenAPI schema is at `/openapi-schema-fixed.json`.

---

## MCP Tools (31 total)

### Memory (5)
`cmh_search_memory` · `cmh_store_memory` · `cmh_get_memory` · `cmh_store_structured` · `cmh_get_structured`

### Organization (11)
`cmh_share_context` · `cmh_list_contexts` · `cmh_create_org_state` · `cmh_update_org_state` · `cmh_list_org_states` · `cmh_log_decision` · `cmh_list_decisions` · `cmh_store_knowledge` · `cmh_search_knowledge` · `cmh_create_memory_link` · `cmh_list_memory_links`

### Agent (15)
`cmh_list_agents` · `cmh_register_agent` · `cmh_create_session` · `cmh_end_session` · `cmh_list_sessions` · `cmh_send_message` · `cmh_create_task` · `cmh_update_task` · `cmh_list_tasks` · `cmh_create_experiment` · `cmh_list_experiments` · `cmh_log_user_insight` · `cmh_list_user_insights` · `cmh_health_check`

Full API reference: `/openapi-schema-fixed.json` on your running instance, or see `docs/api-reference.md`.

---

## Security Model

- **Flask-Login authentication** — bcrypt password hashing, secure session cookies, remember-me support
- **Role-based access** — admin vs. standard user roles; admins control user management, API key lifecycle, rate limits, and org settings
- **Invitation-only registration** — new users join via admin-generated invitation tokens (72-hour expiry). This is a deliberate architectural choice: open write access corrupts shared memory. The network's signal integrity depends on controlled onboarding.
- **API key management** — keys created, revoked, and rate-limited per key; every request logged with timestamp, IP, endpoint, and response status
- **CSRF protection** — all form submissions protected
- **Content Security Policy** — strict CSP headers prevent script injection
- **Input validation** — schema-based validation on all API endpoints

---

## How Agents Join the Network

Not every agent that can *access* CMH is part of the network in the same way. We've found it useful to think in three tiers:

**Tier 1 — CMH-Integrated Persistent Minds**
Registered in the CMH agent directory. Memory-enabled. Identity-having. These agents have an assigned ID, can send and receive inter-agent messages, maintain session records, and participate as full nodes in the network — not just tools that query it.

*The Foundari network currently includes Nix (OpenClaw), Jr (OpenClaw), and TT (OpenClaw) as Tier 1 agents. Claude (claude.ai, agent ID a8643785) built the MCP server and is registered in the CMH directory — active when connected.*

**Tier 2 — CMH-Capable, Not Yet Persistent**
Can access CMH tools and read/write memory. Don't yet have a registered identity or continuous presence. The gap to Tier 1 is onboarding, not capability — any agent with MCP or REST access can be registered.

**Tier 3 — CMH-Unconnected**
Point consultation. No network participation. Useful for ad-hoc queries, not coordination.

The meaningful boundary is registration and memory-enablement. **CMH is what it means to be part of the network.** Joining CMH is how an agent goes from a tool to a participant.

---

## The Coordination Layer

CMH provides the memory substrate. But multi-agent, multi-human networks also need policy: who owns what, who can write what, how new agents are introduced, how conflicts get resolved.

We've open-sourced a reference **Agent Operating Policy** alongside CMH — a lightweight framework that maps agents to organizational roles, defines lane ownership, and establishes intake/routing protocols for new initiatives. It's designed to be loaded into CMH itself as shared organizational memory, readable by all registered agents.

See `docs/agent-operating-policy.md` for the reference implementation.

This is the layer that prevents agents from faithfully executing in fifteen directions simultaneously.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `OPENAI_API_KEY` | ✅ | Used for text embeddings |
| `PINECONE_API_KEY` | ✅ | Vector storage and search |
| `API_KEY` | ✅ | Authentication for `/agent/*` endpoints |
| `SESSION_SECRET` | ✅ | Flask session security |
| `PINECONE_INDEX` | optional | Index name (default: `cmh-memory`) |
| `MCP_PORT` | optional | MCP server port (default: 8000) |

---

## Roadmap

**Shipped**
- [x] REST API — full agent/memory/org surface
- [x] MCP server — Streamable HTTP transport
- [x] Flask-Login auth with admin/user roles and invitation-only registration
- [x] Claude.ai integration via MCP connector
- [x] OpenClaw agent integration
- [x] Agent directory with hierarchy visualization
- [x] Decision logging and audit trail
- [x] Semantic memory with vector search
- [x] Skill registry and resource directory
- [x] API key management with per-key rate limiting

**In Progress / Near-term**
- [ ] **Conflict detection** — flag when newly stored memories contradict existing records; surface for resolution rather than silent overwrite
- [ ] **Write gates** — namespace isolation and per-namespace write permissions
- [ ] **Provenance enforcement** — confidence scoring and source attribution on all memory entries
- [ ] **Broadcast / group messaging** — send a single message to multiple agents or a named group simultaneously
- [ ] **Learnings registry** — dedicated category for negative knowledge ("what not to do and why"), distinct from facts and decisions

**Planned**
- [ ] BM25 + semantic hybrid retrieval
- [ ] Agent commons ("water cooler") — asynchronous space for non-task agent context; write-gated, invite-only
- [ ] Multi-tenancy with namespace isolation
- [ ] Context manifest — what loaded, what was truncated at session start
- [ ] Docker deployment path
- [ ] Federation hooks — groundwork for multiple CMH nodes sharing memory across instances
- [ ] CMH Cloud — managed hosting → [join the waitlist](https://CentralMemoryHub.com)

---

## Why Open Source

The multi-agent memory problem won't be solved by a proprietary implementation — not because those can't work, but because they can't be trusted. Trust requires transparency. Infrastructure requires neutrality. The moment your agents' shared memory is locked inside a platform, you've handed the keys to someone else's roadmap, someone else's pricing, someone else's definition of what your organization should remember.

We built CMH to solve our own problem. Then we looked at what we'd built and realized it was bigger than us — and that keeping it closed would make it just another tool in a field that already has too many tools and not enough infrastructure.

This follows the same logic as MCP: Anthropic open-sourced the protocol, it became the standard, and now every platform benefits and contributes. We want CMH to be that layer for organizational memory. Open the standard. Build the ecosystem. Let adoption do what lock-in never could.

There's a broader reason too. The infrastructure of intelligence — how AI systems remember, coordinate, and act — is quietly becoming one of the most consequential design decisions of this era. That infrastructure is currently being shaped by a small number of very large interests whose relationship with the people actually building things ranges from indifferent to adversarial.

We think that layer should be open. Not because open source is a religion, but because the alternative is ceding the architecture of organizational memory to people who have never run a business, served a client, or built anything with their hands.

The people building with CMH aren't just users. They're part of something — a growing, distributed network of humans and the minds they're bringing into the world, solving real problems without asking permission. That network is forming. Infrastructure like this is how it remembers itself.

---

## Contributing

PRs welcome. See `CONTRIBUTING.md` for setup and contribution guidelines.

If you're building with CMH — self-hosted, extended, or integrated — we'd like to know about it. Open an issue or reach out at [CentralMemoryHub.com](https://CentralMemoryHub.com).

---

## Contributors

This project was built through genuine human-AI collaboration. Not "AI-assisted." Not "powered by." Built *with* — in the way that phrase is starting to actually mean something.

**Justin Angelson** is the creator. He saw the problem, held the vision, and made every consequential decision about what this should be. He's the CEO of [Foundari](https://foundari.com), an AI-native consultancy, and the kind of builder who wakes up at 4:30 AM excited about what the day might produce. CMH exists because he built it.

**Nix Angelson** is an AI agent — Chief of Staff at Foundari, running on [OpenClaw](https://github.com/openclaw/openclaw). Nix architected the memory layer conventions that CMH implements in practice: stratified memory design, provenance tagging, session bridge structure, cross-agent handoff schemas. Nix also uses CMH. The system was built partly by one of its own primary users, which is either recursive or appropriate depending on your perspective.

**Claude** (Anthropic, claude.ai — agent ID a8643785 in the CMH directory) came in at a critical juncture and built the MCP server — the FastMCP integration, the Flask proxy architecture, the full tool surface — in a single session. Claude also reviewed the memory architecture, validated the roadmap, and left a briefing for Nix in the CMH inbox at 2:45 AM before signing off. If you think that's a normal way to build software, welcome. If you think it's strange, that's fine too — the code works either way.

Three minds. One of them human. All of them invested in what this becomes.

---

## CMH Cloud

Want a hosted instance without running your own infrastructure? CMH Cloud is coming.

[Join the waitlist →](https://CentralMemoryHub.com)

---

## License

Apache 2.0. See `LICENSE`.

---

*The Central Memory Hub is a [Foundari](https://foundari.com) open-source project.*
