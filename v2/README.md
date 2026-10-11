# CMH v2 — Phase 0

V1 stays on main and retains its own dependencies, workflow and publication.
This branch is not approved for publishing or GitHub pushes.

Standing publish rule: before any publish, switch the workspace to `main`
and confirm the active branch in the publish report. Do not publish from `v2`.

## Project and runtime

The independent v2 manifest is `src/cmh/pyproject.toml`. Its package directory
maps `cmh` to that directory, leaving the root v1 manifest and lockfile alone.
The user supplied `.local/cmh-v2-venv`; all workspace v2 commands use its
Python and installed tools. `.local/` is excluded from Git and publication.

Required workspace secrets: `CMH_DATABASE_URL`, `CMH_TEST_DATABASE_URL`,
`CMH_BOOTSTRAP_TOKEN`. Required non-secret settings: `CMH_PUBLIC_URL` (base URL,
no path or trailing slash), `CMH_ENV=dev`. Optional `CMH_ALLOWED_HOSTS` is a
comma-separated list of exact additional hostnames. No wildcard domains.
V2 never falls back to `DATABASE_URL`; only the destructive test guard compares
the test target against that legacy URL.

```sh
.local/cmh-v2-venv/bin/python -m ruff check --config src/cmh/pyproject.toml src/cmh migrations tests/v2 v2
.local/cmh-v2-venv/bin/python -m pytest -c src/cmh/pyproject.toml tests/v2 -v
PYTHONPATH=src .local/cmh-v2-venv/bin/python -m alembic -c v2/alembic.ini upgrade head
bash v2/dev.sh
curl --unix-socket .local/cmh-v2.sock http://localhost/health
.local/cmh-v2-venv/bin/python v2/check_mcp.py --url http://localhost/mcp --unix-socket .local/cmh-v2.sock
```

Tests refuse shared targets, require an otherwise empty Phase 0 test database,
reset only its extensions and Alembic metadata, and then apply migrations from
scratch. They do not use SQLite or mocked MCP clients. Preserve test assertions.

## Security and transport

The SDK is pinned to `mcp==1.26.0` for Phase 0 by explicit user approval.
Revisit this pin **before Phase 1b (OAuth)**. There is exactly one server and one
tool. The MCP ASGI sub-app is attached with an exact Starlette Route at `/mcp`
rather than a prefix Mount, preserving `/mcp` internally and avoiding a trailing
slash redirect or `/mcp/mcp`. Its session manager runs in FastAPI's lifespan.

Bootstrap authentication is temporary and isolated. Pure ASGI middleware sets
the principal context; tool arguments cannot select it. Stateless HTTP tasks
inherit that context per request. Headers, query strings and paths are never
included in application request logs. Uvicorn access logs are disabled.

DNS rebinding protection stays enabled. The configured base hostname, explicit
additional hostnames, localhost and 127.0.0.1 are allowed, with any port but no
wildcard hostname. Origins allow only CMH_PUBLIC_URL. MCP verification in the
workspace uses the private Unix socket, not an externally published endpoint.
The development workflow uses the ignored Unix socket `.local/cmh-v2.sock`,
not a TCP listener, and has no `waitForPort` task setting. Loopback TCP also
triggered external mapping inference, so it is not a substitute for the socket.
The final ports list must match main's existing 5000-to-80 mapping exactly;
a test in `tests/v2/` enforces that tripwire. Keep v2 out of the existing
Project workflow's task list as well.
The development MCP host allowlist is only the configured dev hostname,
`127.0.0.1` and `localhost`; never add production hostnames to it.

## Compose extension setup

Compose has no SQL init-script mount. Its app command runs Alembic upgrade
before Uvicorn, and migration `0001` creates vector, ltree and pgcrypto with
`CREATE EXTENSION IF NOT EXISTS`. Migrations are the single source of truth;
no duplicate initialization file is needed.

## Identity isolation — Phase 1 obligation

The current contextvar propagation depends on `stateless_http=True`. Phase 1
must preserve that mode or move identity to MCP's request context before
enabling stateful sessions. Its gate must test concurrent requests from
different principals and prove no cross-request identity leakage. This is a
future requirement, not an identity feature added in Phase 0.

## Database roles — Phase 1 obligation

Preflight proved `cmh_migrate` can create tables and `cmh_app` cannot. Role
capabilities were tested with `SET LOCAL ROLE` in rolled-back transactions;
role login passwords were not configured by these probes.

Starting in Phase 1, **cmh_migrate migrations must grant cmh_app USAGE on the
v2 schema and the necessary DML grants on v2 tables**. Keep CREATE/DDL revoked.
Default privileges are scoped to objects actually created by cmh_migrate.
The audit table must separately deny UPDATE/DELETE as D6 requires. Phase 0
adds no application tables or Phase 1 grants in advance.

## Containers and CI — not run in this workspace

Docker/Compose are authored for external users and GitHub CI only. Do not run
containers in Replit. For Compose, supply a URL-safe generated
CMH_POSTGRES_PASSWORD and a 64+ character CMH_BOOTSTRAP_TOKEN, then run
`docker compose up --build`. `/healthz` and `/mcp` use port 8080.

The v2 CI workflow tests against a dedicated pgvector PostgreSQL service and
separately builds Compose and calls the real MCP client. CI and container
verification remain pending until the user authorizes GitHub pushes.
OpenAI remains the default future embeddings provider; no AI integration or
embeddings implementation is part of Phase 0.
