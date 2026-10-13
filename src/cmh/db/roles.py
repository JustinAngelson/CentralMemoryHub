"""Verify the login role: SET ROLE must never hide privileged login attributes."""

from sqlalchemy import text


def guard_runtime_role(engine, environment):
    if environment == "test":
        return "ok"
    with engine.connect() as connection:
        role = connection.execute(text("""
          SELECT rolname,rolsuper,rolbypassrls,rolcreaterole,rolcreatedb
          FROM pg_roles WHERE rolname=session_user
        """)).mappings().one()
        if any(role[key] for key in ("rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb")):
            raise RuntimeError("Unsafe database role: privileged login role")
        if connection.execute(text("""
          SELECT EXISTS(SELECT 1 FROM pg_tables
            WHERE schemaname='public' AND tableowner=session_user)
        """)).scalar_one():
            raise RuntimeError("Unsafe database role: login owns a v2 table")
        for table in ("audit_events", "entity_versions"):
            exists = connection.execute(text("SELECT to_regclass(:table)"),
                                        {"table": "public." + table}).scalar()
            if exists and connection.execute(text("""
              SELECT has_table_privilege(session_user,:table,'UPDATE')
                  OR has_table_privilege(session_user,:table,'DELETE')
                  OR has_table_privilege(session_user,:table,'TRUNCATE')
            """), {"table": table}).scalar_one():
                label = "audit" if table == "audit_events" else table
                raise RuntimeError("Unsafe database role: " + label + " mutation privileges")
        if connection.execute(text("""
          SELECT has_schema_privilege(session_user,'public','CREATE')
        """)).scalar_one():
            raise RuntimeError("Unsafe database role: schema CREATE privileges")
    return "ok"
