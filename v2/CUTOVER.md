# Explicit operator commands — Phase C

These are not startup hooks. Each stage requires separate approval.
All review files, snapshots, dumps and exports remain under ignored `.local/`.
Never put credential values in arguments, command history, examples or output.

## Targets and review

Local operation retains the local-host guard. Its only additional allowlisted
names are `cmh_v2_rehearsal` and `cmh_v1_rehearsal_snapshot`.
Production apply requires all of:

- `--production`;
- `--target-database cmh_v2`;
- typed `cmh_v2` confirmation (interactive, or `--confirm-database cmh_v2`);
- `CMH_PROD_DATABASE_URL` identifying `cmh_app` on that exact database.

Planning never has a production target. Its source is a private local snapshot.
Use `--plan --delta` with the approved base CSVs already in the output directory.
It creates `roster_review_delta.csv`, `attribution_review_delta.csv` and
`namespace_mapping_delta.csv`, without overwriting the base decisions.
The private approval manifest must contain checksums of all three base files
and all three delta files. Conflicts and missing namespaces fail closed.
Rehearsal approval of a delta is not production approval.

## One-shot legacy handoff

`python v2/legacy_credentials.py --production --database cmh_v2`
prompts for the database confirmation and reads the two legacy secret values
only inside the command. It loads the bootstrap Owner from the database,
creates/reuses the two Owner-sponsored services, and uses native audited
administration to register hash-only `legacy_shared` credentials.
Unused automatically minted native credentials are revoked.
The runtime never imports this command or reads the old variables.
Repeated values report `exists`; collisions and revoked values fail.

For local rehearsal use `--database cmh_v2_rehearsal`, with generated fake
values in the child-process environment, never the actual legacy secrets.

## Rollback export and smoke

Rollback begins by freezing v2 writes and taking a **complete pg_dump** of
`cmh_v2` using the production **cmh_migrate** role, before any republish.
The native JSON export below supplements this backup; it never replaces it.
In the approved operator Shell, run this Python block (not in C0):

```python
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from sqlalchemy.engine import make_url

url = make_url(os.environ["CMH_PROD_MIGRATE_DATABASE_URL"])
if url.username != "cmh_migrate" or url.database != "cmh_v2":
    raise SystemExit("Wrong backup target; do not republish")
directory = Path(".local/release-backups")
directory.mkdir(parents=True, exist_ok=True)
path = directory / ("cmh-v2-full-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".dump")
child = os.environ.copy()
child["PGDATABASE"] = url.set(drivername="postgresql").render_as_string(hide_password=False)
try:
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as handle:
        os.fchmod(handle.fileno(), 0o600)
        completed = subprocess.run(["pg_dump", "--format=custom", "--no-password"],
                                   env=child, stdout=handle, stderr=subprocess.PIPE)
        if completed.returncode:
            raise RuntimeError("Dump failed")
        handle.flush()
        os.fsync(handle.fileno())
    subprocess.run(["pg_restore", "--list", str(path)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
except BaseException:
    raise SystemExit("Backup incomplete or unverified; do not republish") from None
finally:
    child.pop("PGDATABASE", None)
    del url
print("Complete backup verified; retain privately before rollback.")
```

This is a full archive: no schema/table/data filters or privilege/owner exclusions.
Never print the connection, subprocess stderr, archive contents or signup addresses.
If any step fails, stop; retain and label partial evidence privately rather than
republishing. Securely download/verify the full dump and JSON below off the repl.
After Justin confirms recovery copies, remove those release backups from the
workspace before republishing: they must not enter the deployment bundle.
Do not restore over or drop either production database as part of this procedure.

`python v2/export_native.py --production --database cmh_v2 --since <UTC-time> --out .local/release-backups/native-export.json`
requires the same target confirmation. It reads a repeatable, read-only
transaction and writes a new mode-0600 file, refusing to overwrite a file.
The offline bootstrap Owner backup includes all namespaces, not merely the
Owner's ordinary runtime visibility. It includes new native entities, current
snapshots of imported entities whose version changed after `--since` (retaining
`legacy_meta.v1_id`), native sessions/messages, and **waitlist rows** created
after `--since`, including their email addresses. Credentials are metadata only;
authentication hashes/prefixes are excluded. Output/reports show **counts only**;
email addresses occur only inside the private file. The complete archive above
preserves the whole database, including history, deleted rows and other state
outside this supplemental export.

`python v2/check_production.py --url https://your-instance.example`
checks public statuses, framing protection and the OpenAPI origin. It uses
an invalid `/api/waitlist` request, never a real signup.
`--with-token` uses a hidden terminal prompt for optional MCP checks.
For local HTTP rehearsal only, `--unix-socket .local/rehearsal.sock` avoids
creating another TCP listener. Output contains statuses/counts, not content.

## Launch activation is deferred to C2

`v2/replit-cutover.toml` is the prepared, tested complete configuration:
one v2 ASGI service on port 5000, only 5000 → 80, with matching workflow.
The active `.replit` is intentionally unchanged in C0. At the approved C2
merge, apply the template using Replit's configuration validator; confirm the
actual main branch/SHA and sole port mapping before offering Publish.
Do not invoke the validator against a nested clone during C0: it targets the
workspace root.

## C2 source rollback prepared immediately after merge (CR2)

At C2, record both known pre-cutover references privately:
v1 deployed SHA `ddf0295`; workspace main `eb13565` (local empty publish
checkpoint, **never push it**). Confirm the actual references at the C2 gate;
these recorded values are not a fresh production check during C0.

Immediately after Justin merges v2 into main **with a merge commit**, record
the exact full merge SHA. In the clean private Git worktree, prepare recovery:

```sh
git fetch https://github.com/JustinAngelson/centralmemoryhub.git main
MERGE_SHA=<approved-full-v2-to-main-merge-SHA>
git switch -c rollback/v1-restore "$MERGE_SHA"
git revert -m 1 "$MERGE_SHA"
git push https://github.com/JustinAngelson/centralmemoryhub.git HEAD:refs/heads/rollback/v1-restore
gh pr create --repo JustinAngelson/centralmemoryhub --base main \
  --head rollback/v1-restore --draft --title "Restore v1 source if cutover rollback is approved" \
  --body "Draft recovery only. Reverts the v2-to-main merge against first-parent v1. Do not merge unless Justin approves rollback."
```

Verify that the merge's first parent is the approved v1 main and that the draft
diff restores v1 launch/configuration with only 5000 → 80. Record the draft PR
URL before publishing v2. Do **not** merge the draft during preparation. Only
these explicitly named refs may be pushed; never force-push, push all refs or tags.
These are future C2 instructions, not authorization to push this branch in C0.

### Exact proposed workspace-main alignment (include in the C1 report)

At approved C2 only, on the **root workspace**, require a clean tracked worktree,
branch main at `eb13565`, verified `MERGE_SHA` equal to GitHub main, and preserve
ignored `.local/` files plus the production configuration inventory. Then:

```sh
git fetch https://github.com/JustinAngelson/centralmemoryhub.git main
MERGE_SHA=<approved-full-v2-to-main-merge-SHA>
test "$(git rev-parse FETCH_HEAD)" = "$MERGE_SHA" || exit 1
test "$(git branch --show-current)" = main || exit 1
test "$(git rev-parse --short=7 HEAD)" = eb13565 || exit 1
test -z "$(git status --porcelain --untracked-files=no)" || exit 1
git branch local/v1-publish-checkpoint eb13565
git reset --keep "$MERGE_SHA"
test "$(git rev-parse HEAD)" = "$MERGE_SHA" || exit 1
```

This only realigns a **local** ref, with the empty checkpoint preserved locally.
No root main or checkpoint push occurs, and no merge carries `eb13565` into
GitHub. Stop on any failed precondition; do not fall back to `reset --hard`.
Reapply only approved deployment configuration overlays through the validator,
confirm the main SHA and sole 5000 → 80 mapping, then follow Justin's publish gate.

### Actual rollback

First freeze writes, obtain/verify the full backup and supplemental export, and
secure the recovery copies as above. **Justin merges the prepared draft PR**.
The workspace then fetches GitHub main and uses `git merge --ff-only FETCH_HEAD`
from the clean cutover main (or stops for review if not fast-forwardable).
Confirm branch main at the rollback merge SHA, restore/verify approved v1
production configuration and current legacy secrets, verify only 5000 → 80,
and publish with Justin's go. Verify v1 health and unauthenticated MCP 401.
Do not rely on deployment history; do not reset to an old SHA and push it.

## Partner onboarding: Owner enters only their own password (CR3)

After single-Owner bootstrap over HTTPS using the private getpass procedure,
reuse that authenticated in-memory client for the two approved Partner profiles.
`v2/partner_accounts.py:create_partner(client, origin, profile)` calls the native
admin API with kind human, role partner and tier 3. It generates a fresh
`secrets.token_urlsafe(48)` throwaway password in memory, never prompts for a
Partner password, never prints or writes it, and returns only the principal ID.
Only the native salted password hash is stored by account administration.
Use the approved private roster (fictional profiles only in public examples);
if a principal already exists, reuse it rather than creating/resetting it.

Justin enters only the Owner password; the bootstrap token and approved Owner
profile still use the private getpass steps. Partner real logins come later via
an Owner reset. Do not save throwaway passwords, response bodies, client/cookie
objects, HTTP wire traces, or request payloads; close the client when done.

## Production import: detached execution only

At the separately approved production apply gate, use the reviewed private
files and a supervised detached job. Never put an import under a short tool
timeout or print connection values. In the operator Shell:

```sh
umask 077
mkdir -p .local/release-backups
nohup sh -c '
  .local/cmh-v2-venv/bin/python v2/import_v1.py \
    --apply --production --target-database cmh_v2 --confirm-database cmh_v2 \
    --source-database cmh_v1_snapshot \
    --defaults .local/cmh-v2-import/review-defaults.json \
    --orgs .local/cmh-v2-import/orgs.csv --out .local/cmh-v2-import
  result=$?
  printf "%s\n" "$result" > .local/release-backups/import.exit
  exit "$result"
' </dev/null >.local/release-backups/import.log 2>&1 &
printf "%s\n" "$!" >.local/release-backups/import.pid
```

Poll the PID and eventual `import.exit` without starting duplicate imports.
Review only the credential-safe counts/status log; zero exit plus row accounting,
valid chain and zero active import credentials are required, not just a dead PID.
Before each attempt archive previous status/PID/log files privately so a stale
zero exit cannot be mistaken for success. On interruption revoke orphaned
import credentials natively before resuming the same target; do not erase the
target or audit chain. Secure/download/delete these release files before any
publish as described above.
