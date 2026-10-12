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
        exists = connection.execute(text("SELECT to_regclass('public.audit_events')")).scalar()
        if exists and connection.execute(text("""
          SELECT has_table_privilege(session_user,'audit_events','UPDATE')
              OR has_table_privilege(session_user,'audit_events','DELETE')
              OR has_table_privilege(session_user,'audit_events','TRUNCATE')
        """)).scalar_one():
            raise RuntimeError("Unsafe database role: audit mutation privileges")
        if connection.execute(text("""
          SELECT has_schema_privilege(session_user,'public','CREATE')
        """)).scalar_one():
            raise RuntimeError("Unsafe database role: schema CREATE privileges")
    return "ok"
