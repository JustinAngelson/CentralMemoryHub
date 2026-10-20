# Workspace database boundary

Do not start the workspace CMH app until this change has merged and the Owner
has explicitly lifted the standing workspace-run restriction. No database or
secret is provisioned by this change.

## Runtime guard

`create_app()` checks the target before configuring logging, constructing an
engine, reading the database, or probing embeddings.

Only Replit's deployment-provided `REPLIT_DEPLOYMENT=1` marks a published runtime.
An absent marker means workspace/non-production; any other value is refused.
`CMH_ENV=prod` alone never authorizes a production database connection.

Reference: https://docs.replit.com/features/project-setup/configuration

In non-production, compare the server and database with
`CMH_PROD_DATABASE_URL` when present, ignoring credentials and treating Neon
direct/pooler hostnames as the same server. Also refuse database `cmh_v2` on
any Neon endpoint even without that reference: this deliberately errs on the
side of safety. Invalid or ambiguous URL routing is refused. Errors contain
fixed reasons only, not connection details.

## Proposed development database (not created)

- Server: the **non-production** server used by `CMH_TEST_DATABASE_URL`.
- Development database: `cmh_v2_dev`, distinct from `cmh_v2_test` and production.
  It may already exist from Phase 0; verify before provisioning, never replace it.
- Runtime role: that server's `cmh_app`, never production credentials.
- New workspace secret: **`CMH_DEV_DATABASE_URL`**, pointing only at this
  development database. A copy syncing to production must convey no production
  privileges. The deployment does not read this variable.
- Keep `CMH_TEST_DATABASE_URL` targeting the separate test database.

After separate approval, use `v2/init_database.py` with process-local
`CMH_ADMIN_DATABASE_URL`, `CMH_DATABASE_URL` and `CMH_MIGRATE_DATABASE_URL`
overrides that **all target this non-production server**. Use the established
development role passwords, not production passwords. This helper creates or
reuses `cmh_v2_dev` and `cmh_v2_test`, initializes vector/ltree/pgcrypto and
schema access, and sets the application/migration role passwords; therefore
do not run it blindly or against production. Run Alembic and seed against the
development database afterward with the development migration/application
connections. Do not rebuild the test database or reset established passwords
as an incidental part of this proposal.

The workspace workflow overrides `CMH_DATABASE_URL` from
`CMH_DEV_DATABASE_URL` for that command only, sets `CMH_ENV=dev`, and uses the
existing `.local/cmh-v2-venv/bin/python`. Missing dev configuration stops the
shell before Python is invoked; it never falls back to the workspace's
production-valued `CMH_DATABASE_URL`. Deployment run/build commands are unchanged.

The repository's previous tracked `.replit` still used the v1 launch command;
the workspace had the approved v2 cutover configuration as a skip-worktree
overlay. This change records that existing active deployment configuration
alongside the workflow correction. It does not change the active deployment
run or build command.

## Verification without workspace app execution

Offline tests in `tests/operators/test_startup_database_guard.py` exercise
target checks, verify guard placement from the syntax tree, and check that a
missing dev secret stops the workflow command before app invocation.

Application construction and health checks in
`tests/v2/test_workspace_startup_integration.py` run only in isolated CI for this
change, against its disposable PostgreSQL service, with no production secrets.
No workspace workflow, CMH app, migration, seed, or dependency installation is
needed to verify the offline guard.
