"""Prepare one C3 credential through native HTTPS; run only in a private terminal."""
import sys

sys.dont_write_bytecode = True

import argparse
import json
import re
from datetime import UTC, datetime

import c3_common as common


def active(row, now):
    expiry = row.get("expires_at")
    return not row.get("revoked_at") and (
        not expiry or datetime.fromisoformat(expiry) > now
    )


def revoke(client, identity):
    common.request(client, "POST", f"/admin/api/credentials/{identity}/revoke",
                   json={"reason": "C3 operator rotation or failed issuance cleanup"})


def mint(client, subject, template, *, rotate=False):
    if subject["status"] != "active":
        raise common.OperatorError("Principal is not active.")
    existing = common.request(client, "GET", "/admin/api/credentials")["credentials"]
    now = datetime.now(UTC)
    old = [row for row in existing
           if str(row["principal_id"]) == str(subject["id"])
           and row["kind"] != "legacy_shared" and active(row, now)]
    if old and not rotate:
        raise common.OperatorError("Active non-legacy credential exists; use --rotate explicitly.")
    made = None
    try:
        body = common.request(client, "POST", "/admin/api/credentials", json={
            "principal_id": str(subject["id"]), "template": template,
            "name": "c3-" + subject["slug"],
        })
        made = body.get("credential", body)
        prefix = "cmh_pk_" if template == "personal-ai-client" else "cmh_ak_"
        if (
            not made.get("id") or str(made.get("principal_id")) != str(subject["id"])
            or not isinstance(made.get("token"), str)
            or not made["token"].startswith(prefix)
            or not re.fullmatch(r"cmh_[pa]k_[A-Za-z0-9_-]+", made["token"])
            or not isinstance(made.get("scopes"), list)
            or not all(isinstance(scope, str) for scope in made["scopes"])
        ):
            raise common.OperatorError("Credential response validation failed.")
        # Exactly one standard-template issuance; never call the rotate endpoint,
        # which copies an old credential's potentially nonstandard scopes.
        for row in old:
            revoke(client, row["id"])
        if old:
            listed = common.request(client, "GET", "/admin/api/credentials")["credentials"]
            by_id = {str(row["id"]): row for row in listed}
            if any(str(row["id"]) not in by_id or
                   not by_id[str(row["id"])].get("revoked_at") for row in old):
                raise common.OperatorError("Old credential revocation verification failed.")
        return made
    except BaseException:
        if isinstance(made, dict) and made.get("id"):
            try:
                revoke(client, made["id"])
            except BaseException:  # noqa: BLE001 — cleanup failure must never expose a token
                raise common.OperatorError(
                    "Issuance cleanup failed; inspect native credentials before retrying."
                ) from None
        raise


def show_credential(slug, credential, output):
    print("COPY NOW, then run clear and clear terminal scrollback. Do not paste into chat.",
          file=output)
    print("principal_slug " + slug, file=output)
    print("credential_id " + str(credential["id"]), file=output)
    print("scopes " + json.dumps(sorted(credential["scopes"])), file=output)
    print(credential["token"], file=output)
    print("COPY NOW, then run clear and clear terminal scrollback.", file=output, flush=True)


def main(argv=None):
    common.quiet()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("principal_slug")
    parser.add_argument("--rotate", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise common.OperatorError("Private interactive terminal required; redirection refused.")
        template = common.TEMPLATES.get(args.principal_slug)
        if not template:
            raise common.OperatorError("Principal is outside the approved C3 roster.")
        with common.readonly_connection() as conn:
            subject = common.lookup(conn, args.principal_slug)
        # Close the read transaction before any HTTPS operation.
        with common.https_client() as client:
            made = None

            def cleanup_after_logout_failure():
                if made is not None:
                    revoke(client, made["id"])

            try:
                with common.owner_session(client, on_logout_failure=cleanup_after_logout_failure):
                    made = mint(client, subject, template, rotate=args.rotate)
                show_credential(subject["slug"], made, sys.stdout)
            except BaseException:
                # A failed logout triggers native revocation before cookie
                # cleanup. An interrupted terminal output is indeterminate;
                # never retry issuance or print the token again automatically.
                if made is not None:
                    raise common.OperatorError(
                        "Post-mint session/output failed; inspect native credentials before retrying."
                    ) from None
                raise
        return 0
    except common.OperatorError as error:
        print(str(error), file=sys.stderr)
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 — no traceback/HTTP body disclosure
        print("C3 mint stopped; check native credentials before retrying.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
