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

`python v2/export_native.py --production --database cmh_v2 --since <UTC-time> --out .local/native-export.json`
requires the same target confirmation. It reads a repeatable, read-only
transaction and writes a new mode-0600 file, refusing to overwrite a file.
The offline bootstrap Owner backup includes all namespaces, not merely the
Owner's ordinary runtime visibility. Credentials are metadata only, waitlist
is counts only, and authentication hashes/prefixes are excluded.
This is the requested newly-created-native-record export, not a full backup
of edits to previously imported entities.

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
