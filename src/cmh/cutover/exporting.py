"""Read-only, RLS-aware rollback data. Never export authentication material."""
from sqlalchemy import text


def export_records(connection, since, owner):
    connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    if owner.principal.get("role") != "owner":
        raise ValueError("Bootstrap Owner required")
    # Explicit offline Owner rollback backup, not a runtime read API: include
    # all namespaces so private client writes are not silently lost on rollback.
    visible = [str(value) for value in connection.execute(text("SELECT id FROM namespaces")).scalars()]
    connection.execute(text("SELECT set_config('cmh.readable_namespaces',:ids,true)"),
                       {"ids": ",".join(visible)})
    output = {}
    counts = {}
    output["entities"] = [dict(r) for r in connection.execute(text("""
      SELECT e.*,v.snapshot AS current_version_snapshot FROM entities e JOIN entity_versions v
        ON v.entity_id=e.id AND v.version=e.current_version
      WHERE (e.created_at>:since AND e.legacy_meta->>'v1_id' IS NULL)
         OR (e.legacy_meta->>'v1_id' IS NOT NULL AND v.version>1 AND v.changed_at>:since)
    """), {"since": since}).mappings()]
    # Embedding internals are not application content and must not bloat rollback files.
    for row in output["entities"]:
        row["current_version_snapshot"] = {k: v for k, v in row["current_version_snapshot"].items()
                                            if not k.startswith("__")}
    for table in ("sessions", "messages"):
        created = "started_at" if table == "sessions" else "created_at"
        output[table] = [dict(r) for r in connection.execute(text(f"""
          SELECT * FROM {table} WHERE {created}>:since AND legacy_meta->>'v1_id' IS NULL
        """), {"since": since}).mappings()]
    output["credentials"] = [dict(r) for r in connection.execute(text("""
      SELECT id,principal_id,name,kind,scopes,created_at,expires_at,revoked_at,issued_by,template_id
      FROM credentials WHERE created_at>:since
    """), {"since": since}).mappings()]
    # Signup addresses belong only in the private 0600 artifact, never reports.
    output["waitlist"] = [dict(r) for r in connection.execute(text("""
      SELECT * FROM waitlist WHERE created_at>:since
    """), {"since": since}).mappings()]
    counts.update({key: len(value) for key, value in output.items()})
    return output, counts
