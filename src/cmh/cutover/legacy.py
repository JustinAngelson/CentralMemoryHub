"""One-shot legacy handoff. Secret values are never returned or logged."""
from sqlalchemy import text

from cmh.policy.scopes import expand
from cmh.services import administration, management
from cmh.services.accounts import digest


def load_legacy(service, owner, environ):
    if owner.principal["role"] != "owner" or owner.principal["kind"] != "human":
        raise ValueError("Bootstrap Owner required")
    # Validate both before any mutation. Reading actual secrets happens only here.
    values = {slug: environ[key] for slug, key in (
        ("legacy-mcp", "MCP_BEARER_TOKEN"), ("legacy-rest", "API_KEY"))}
    if any(not value for value in values.values()) or len(set(values.values())) != 2:
        raise ValueError("Two distinct nonempty legacy values required")
    output = []
    for slug, value in values.items():
        with service.engine.connect() as conn:
            template = conn.execute(text("""SELECT * FROM credential_templates
              WHERE name='openclaw-agent-standard' AND active""")).mappings().one()
            scopes = expand(template["scopes"]) if slug == "legacy-mcp" else [
                "memory.read", "memory.write"]
            subject = conn.execute(text("SELECT * FROM principals WHERE slug=:slug"),
                                   {"slug": slug}).mappings().first()
        if not subject:
            result = management.create_principal(service, owner, {
                "kind": "service", "slug": slug, "display_name": slug,
                "sponsor_id": str(owner.id), "template": "service-integration", "scopes": scopes,
                "credential_name": "unused-native-handoff",
            }, approved=True)
            if "principal" not in result or "credential" not in result:
                raise ValueError("Service registration refused")
            subject = result["principal"]
            administration.revoke(service, owner, result["credential"]["id"],
                                  {"reason": "Legacy handoff uses shared credential only"})
        if subject["kind"] != "service" or subject["sponsor_id"] != owner.id:
            raise ValueError("Legacy service ownership mismatch")
        grants = [("org", "write")] + ([("org.clients", "read")] if slug == "legacy-mcp" else [])
        for path, access in grants:
            with service.engine.connect() as conn:
                found = conn.execute(text("SELECT id FROM namespaces WHERE path=CAST(:path AS ltree)"),
                                     {"path": path}).scalar()
            if not found:
                administration.namespace_create(service, owner, {"path": path})

            def grant(conn, path=path, access=access, subject=subject):
                conn.execute(text("""INSERT INTO namespace_grants(principal_id,namespace_id,access,granted_by)
                  SELECT :id,id,:access,:owner FROM namespaces WHERE path=CAST(:path AS ltree)
                  ON CONFLICT(principal_id,namespace_id,access) DO NOTHING"""),
                             {"id": subject["id"], "owner": owner.id, "path": path, "access": access})
            service.perform(owner, "grants.admin", change=grant, audit_operation="cutover.legacy_grant")
        with service.engine.connect() as conn:
            existing = conn.execute(text("""SELECT principal_id,kind,revoked_at FROM credentials
              WHERE token_hash=:hash"""), {"hash": digest(value)}).mappings().first()
        if existing:
            if (existing["principal_id"] != subject["id"] or existing["kind"] != "legacy_shared"
                    or existing["revoked_at"] is not None):
                raise ValueError("Legacy credential collision or revoked value")
            service.perform(owner, "credentials.admin", audit_operation="cutover.legacy_exists")
            status = "exists"
        else:
            result = administration.import_legacy(service, owner, {
                "principal_id": subject["id"], "token": value, "name": slug})
            if result.get("outcome") == "DENY":
                raise ValueError("Legacy credential import refused")
            status = "created"
        output.append({"slug": slug, "status": status})
    return output
