"""Explicitly read-only private snapshot access; forbidden legacy variables are never read."""
import os
import re
from contextlib import contextmanager

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from cmh.importing.plan import EXCLUDED

INVENTORY = {
    "agent_directory", "agent_sessions", "agent_skills", "agent_tasks",
    "api_keys", "api_request_logs", "decision_log", "experiments",
    "gpt_messages", "invitation_tokens", "kb_index", "memory_links",
    "org_profile", "org_state", "project_decisions", "resources",
    "shared_contexts", "skill_files", "skills", "unstructured_data",
    "user_insights", "user_skills", "users", "waitlist",
}
SOURCE_ENV = {"CMH_TEST_DATABASE_URL", "CMH_V1_SNAPSHOT_URL"}
FORBIDDEN_COLUMNS = {
    "stored_filename", "file_path", "path", "upload_url", "url", "file_data",
    "file_bytes", "bytes", "blob", "email", "password", "password_hash", "api_key",
}


def validate_snapshot_database(name):
    if not re.fullmatch(r"cmh_v1_(snapshot|fixture_[0-9a-f]+)", name):
        raise ValueError("Source must be an explicitly named private snapshot database")


def connection_from_env(env_name, database):
    if env_name not in SOURCE_ENV | {"CMH_DATABASE_URL", "CMH_MIGRATE_DATABASE_URL"}:
        raise ValueError("Unapproved database environment variable")
    try:
        info = conninfo_to_dict(os.environ[env_name].replace(
            "postgresql+psycopg://", "postgresql://"))
    except (KeyError, psycopg.Error, ValueError):
        raise ValueError("Required connection configuration is unavailable") from None
    if database.startswith("cmh_v1_"):
        if env_name not in SOURCE_ENV:
            raise ValueError("Unapproved snapshot source environment variable")
        validate_snapshot_database(database)
        if info.get("host") not in {"helium", "127.0.0.1", "localhost", "db", "postgres"}:
            raise ValueError("Dry-run source must be on the isolated local server")
    else:
        if env_name not in {"CMH_TEST_DATABASE_URL", "CMH_DATABASE_URL", "CMH_MIGRATE_DATABASE_URL"}:
            raise ValueError("Unapproved target metadata environment variable")
        if database not in {"cmh_v2_import", "cmh_v2_test"}:
            raise ValueError("Plan target must be an isolated v2 database")
        if info.get("host") not in {"helium", "127.0.0.1", "localhost", "db", "postgres"}:
            raise ValueError("Dry-run target must be on the isolated local server")
    return make_conninfo(**{**info, "dbname": database})


@contextmanager
def source_connection(url):
    info = conninfo_to_dict(url)
    validate_snapshot_database(info["dbname"])
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=15) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        conn.execute("SET ROLE cmh_v1_reader")
        role = conn.execute("""SELECT current_user AS name,current_setting(
            'transaction_read_only') AS read_only""").fetchone()
        if role["name"] != "cmh_v1_reader" or role["read_only"] != "on":
            raise ValueError("Snapshot reader role/read-only guard failed")
        yield conn
        conn.rollback()


def read_source(url, include_waitlist=False):
    with source_connection(url) as conn:
        # One catalog read; no excluded data, emails, keys or file bytes loaded.
        names = {r["tablename"] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()}
        if names != INVENTORY:
            raise ValueError("Snapshot inventory differs from approved 24-table schema")
        columns = conn.execute("""SELECT table_name,column_name,data_type FROM
            information_schema.columns WHERE table_schema='public'
            ORDER BY table_name,ordinal_position""").fetchall()
        primary = conn.execute("""SELECT c.relname AS table_name,a.attname AS column_name
            FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,position)
            JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.attnum
            WHERE n.nspname='public' AND i.indisprimary ORDER BY c.relname,k.position""").fetchall()
        primary_keys = {}
        for row in primary:
            primary_keys.setdefault(row["table_name"], []).append(row["column_name"])
        tables, counts = {}, {}
        for table in sorted(INVENTORY):
            counts[table] = conn.execute(sql.SQL("SELECT count(*) AS n FROM public.{}").format(
                sql.Identifier(table))).fetchone()["n"]
            if table in EXCLUDED or (table == "waitlist" and not include_waitlist):
                continue
            selected = [r["column_name"] for r in columns if r["table_name"] == table
                        and (r["column_name"] not in FORBIDDEN_COLUMNS
                             or (table == "waitlist" and r["column_name"] == "email"))
                        and r["data_type"] != "bytea"]
            tables[table] = conn.execute(sql.SQL("SELECT {} FROM public.{}").format(
                sql.SQL(",").join(map(sql.Identifier, selected)),
                sql.Identifier(table))).fetchall()
        return {"tables": tables, "counts": counts, "primary_keys": primary_keys}


def target_state(url):
    native_url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(native_url, row_factory=dict_row, connect_timeout=15) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        names = [r["tablename"] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        if "audit_events" not in names or "alembic_version" not in names:
            raise ValueError("Plan target must be migrated before planning")
        counts = {name: conn.execute(sql.SQL("SELECT count(*) AS n FROM public.{}").format(
            sql.Identifier(name))).fetchone()["n"] for name in names}
        maximum = conn.execute("SELECT coalesce(max(seq),0) AS seq FROM audit_events").fetchone()["seq"]
        conn.rollback()
    return {"counts": counts, "audit_max_seq": maximum}
