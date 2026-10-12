"""Single permission evaluator. No mutations, chain locks, or nested audit writes."""

from sqlalchemy import text

from cmh.policy.scopes import ceiling, envelope


def deny(code, step=1):
    return {
        "outcome": "DENY", "code": code, "step": step,
        "detail": "The request does not satisfy " + code + ".",
        "remedy": "Use the correct authentication surface or ask the Owner to review access.",
    }


def allow():
    return {"outcome": "ALLOW", "code": "OK", "step": 5, "detail": "Access permitted",
            "remedy": ""}


def principal(connection, identity):
    row = connection.execute(text("SELECT * FROM principals WHERE id=:id"), {"id": identity})
    value = row.mappings().first()
    return dict(value) if value else None


def namespace(connection, path):
    row = connection.execute(text(
        "SELECT * FROM namespaces WHERE path=CAST(:path AS ltree)"
    ), {"path": path}).mappings().first()
    return dict(row) if row else None


def can_access(connection, subject, path, write=False):
    node = namespace(connection, path)
    if not node:
        return False
    if path.startswith("people.") and path.endswith(".private"):
        if node["owner_principal_id"] == subject["id"]:
            return True
        # Owner status is not an implicit grant into someone else's private data.
        if subject["role"] == "owner":
            return False
    elif subject["role"] == "owner":
        return True
    if path.startswith("agents.") and path.endswith(".private"):
        owner = principal(connection, node["owner_principal_id"])
        if owner and (owner["id"] == subject["id"] or owner["sponsor_id"] == subject["id"]):
            return True
    if subject["role"] == "external" and path == "inbox":
        return True
    return bool(connection.execute(text("""
        SELECT 1 FROM namespace_grants g JOIN namespaces n ON n.id=g.namespace_id
        WHERE g.principal_id=:id AND n.path @> CAST(:path AS ltree)
          AND (:write=false OR g.access='write') LIMIT 1
    """), {"id": subject["id"], "path": path, "write": write}).scalar())


def sponsor_ceiling(connection, subject, path, write=False, operation=None):
    if subject["kind"] == "human":
        return True
    sponsor = principal(connection, subject["sponsor_id"])
    if not sponsor or sponsor["status"] != "active":
        return False
    if subject["kind"] == "agent" and subject["tier"] > sponsor["tier"]:
        return False
    if subject["kind"] == "service" and operation and (
        operation.startswith("sync.") or operation == "entities.write"
    ):
        return sponsor["role"] == "owner"
    if operation and operation not in envelope(sponsor):
        return False
    if path is None:
        return True
    # Templates' own-agent namespaces are implicitly writable by their sponsor.
    if path == "agents." + subject["slug"] + ".private":
        return True
    return can_access(connection, sponsor, path, write)


def evaluate(connection, context, operation, path=None):
    subject = context.principal
    if not subject:
        return deny("AUTH_MISSING")
    if subject["kind"] != "human" and operation in (
        "principals.admin", "credentials.admin", "credentials.issue_sponsored",
    ):
        return deny("PRINCIPAL_CREATION_FORBIDDEN", 6)
    credential = context.credential
    if credential and credential["ai_client"] and ceiling(operation):
        return deny("AI_CLIENT_CEILING", 2)
    if credential and operation not in credential["scopes"]:
        return deny("AI_CLIENT_CEILING" if credential["ai_client"] and ceiling(operation)
                    else "SCOPE_MISSING", 2)
    tier_scopes = set(credential["scopes"]) if subject["kind"] == "service" else envelope(subject)
    if operation not in tier_scopes:
        return deny("TIER_FORBIDDEN", 3)
    write = not operation.endswith(".read")
    if subject["role"] == "external" and write and path != "inbox":
        return deny("TIER_FORBIDDEN", 3)
    existing = namespace(connection, path) if path else None
    if not sponsor_ceiling(connection, subject, path if existing else None, write, operation):
        return deny("SPONSOR_CEILING", 4)
    if path:
        node = existing
        if not node:
            parent = path.rsplit(".", 1)[0] if "." in path else ""
            return deny("NAMESPACE_NOT_FOUND" if parent and can_access(
                connection, subject, parent,
            ) else "NAMESPACE_FORBIDDEN", 5)
        if not can_access(connection, subject, path, write):
            return deny("NAMESPACE_FORBIDDEN", 5)
    return allow()
