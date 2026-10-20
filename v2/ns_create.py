"""Owner-operated flag namespaces; prepare offline, run only with approval."""
import sys

sys.dont_write_bytecode = True

import argparse
import json
import re
from datetime import datetime
from uuid import UUID

import c3_common as common

VERIFICATION_ERROR = "Namespace creation could not be verified."


def validate(path, description):
    if (not re.fullmatch(r"org\.(?:clients\.)?[a-z0-9][a-z0-9_-]{0,62}", path)
            or path == "org.finance" or path.startswith("org.finance.")):
        raise common.OperatorError("Namespace path is not permitted.")
    if (not 1 <= len(description) <= 200 or not description.strip()
            or description.splitlines() != [description]):
        raise common.OperatorError("Description must be 1–200 characters without newlines.")


def lookup(connection, path):
    return connection.execute("""
        SELECT id,path::text AS path,mode,governed,created_at
        FROM namespaces WHERE path=%s::ltree
    """, (path,)).fetchone()


def metadata(row, path):
    try:
        if (not row or row["path"] != path or row["mode"] not in ("flag", "queue")
                or not isinstance(row["governed"], bool)):
            raise ValueError
        identity = str(UUID(str(row["id"])))
        at = row["created_at"]
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise ValueError
        return {
            "path": path, "mode": row["mode"], "governed": row["governed"],
            "namespace_id_prefix": identity[:8], "created_at": at.isoformat(),
        }
    except (KeyError, TypeError, ValueError):
        raise common.OperatorError(VERIFICATION_ERROR) from None


def create_namespace(path, description):
    validate(path, description)
    # Close the cmh_app READ ONLY transaction before any authentication/write.
    with common.readonly_connection() as connection:
        existing = lookup(connection, path)
        if existing is not None:
            return {**metadata(existing, path), "status": "already exists"}
        if lookup(connection, path.rsplit(".", 1)[0]) is None:
            raise common.OperatorError("Parent namespace does not exist.")
    with common.https_client() as client, common.owner_session(client):
        # Never retry: a failed response may follow a committed creation.
        common.request(client, "POST", "/admin/api/namespaces", json={
            "path": path, "description": description, "mode": "flag",
        })
    with common.readonly_connection() as connection:
        row = lookup(connection, path)
        result = metadata(row, path)
        if result["mode"] != "flag" or result["governed"] is not False:
            raise common.OperatorError(VERIFICATION_ERROR)
    return result


def main(argv=None):
    common.quiet()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--description", required=True)
    args = parser.parse_args(argv)
    try:
        result = create_namespace(args.path, args.description)
        # Only verified, allowlisted metadata is emitted, after Owner logout.
        print(json.dumps(result))
        return 0
    except common.OperatorError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 — never leak bodies/credentials
        print(json.dumps({
            "error": "Namespace creation stopped; inspect native status before retrying.",
        }), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
