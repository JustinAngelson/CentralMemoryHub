"""Owner-operated legacy retirement. Prepare offline; run only with separate approval."""
import sys

sys.dont_write_bytecode = True

import argparse
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import c3_common as common
from c3_reports import legacy_usage

LEGACY_SLUGS = {"legacy-mcp", "legacy-rest"}


def utcnow():
    return datetime.now(UTC)


def active(row, now):
    expiry = row.get("expires_at")
    return not row.get("revoked_at") and (
        not expiry or datetime.fromisoformat(expiry) > now
    )


def credentials(client):
    rows = common.request(client, "GET", "/admin/api/credentials").get("credentials")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise common.OperatorError("Credential listing could not be verified.")
    return rows


def retire(client, subject):
    """Use the authenticated native API only; never retry indeterminate writes."""
    now = utcnow()
    selected = [
        row for row in credentials(client)
        if str(row.get("principal_id")) == str(subject["id"])
        and row.get("kind") == "legacy_shared" and active(row, now)
    ]
    # Validate every ID before sending the first mutation.
    ids = [str(UUID(str(row["id"]))) for row in selected]
    for identity in ids:
        common.request(client, "POST", f"/admin/api/credentials/{identity}/revoke",
                       json={"reason": "C3 approved legacy retirement after 24h without use"})
    listed = credentials(client)
    by_id = {str(row.get("id")): row for row in listed}
    revoked = []
    for identity in ids:
        row = by_id.get(identity)
        if (not row or not row.get("revoked_at")
            or str(row.get("principal_id")) != str(subject["id"])
            or row.get("kind") != "legacy_shared"):
            raise common.OperatorError("Legacy revocation could not be verified.")
        at = datetime.fromisoformat(row["revoked_at"])
        if at.tzinfo is None:
            raise common.OperatorError("Revocation timestamp could not be verified.")
        revoked.append({"credential_id_prefix": identity[:8], "revoked_at": at.isoformat()})
    remaining = [row for row in listed
                 if str(row.get("principal_id")) == str(subject["id"]) and active(row, utcnow())]
    legacy_count = sum(row.get("kind") == "legacy_shared" for row in remaining)
    if legacy_count:
        raise common.OperatorError("Active legacy credentials remain; inspect before retrying.")
    return {"principal_slug": subject["slug"], "revoked": revoked,
            "active_credentials_after": len(remaining),
            "active_legacy_credentials_after": legacy_count}


def main(argv=None):
    common.quiet()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("principal_slug")
    args = parser.parse_args(argv)
    try:
        slug = args.principal_slug
        if slug not in LEGACY_SLUGS:
            raise common.OperatorError("Only the two legacy principals are permitted.")
        # Same read-only helper/report as c3_legacy_usage.py; max audit time
        # includes transport. Close SQL before confirmation or Owner login.
        with common.readonly_connection() as conn:
            subject = common.lookup(conn, slug)
            if subject["slug"] != slug:
                raise common.OperatorError("Legacy principal lookup did not match.")
            seen = legacy_usage(conn, [subject], utcnow())["last_seen"]
        if len(seen) != 1 or seen[0]["principal"] != slug:
            raise common.OperatorError("Usage could not be verified.")
        last_seen = seen[0]["last_seen"]
        if last_seen is not None and (
            last_seen.tzinfo is None or utcnow() - last_seen < timedelta(hours=24)
        ):
            raise common.OperatorError("Less than 24 hours without use; retirement refused.")
        if input("Type the exact legacy principal slug to confirm revocation: ") != slug:
            raise common.OperatorError("Confirmation did not match.")
        with common.https_client() as client, common.owner_session(client):
            result = retire(client, subject)
        # Only emit the allowlisted result after revocation verification/logout.
        print(json.dumps(result))
        return 0
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 — no credential-bearing errors/bodies
        print("Legacy retirement stopped; inspect native status before retrying.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
