"""Isolated CI/Compose role initialization. Never used against workspace v1."""

import os

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url


def initialize():
    administrative = make_url(os.environ["CMH_ADMIN_DATABASE_URL"]).set(drivername="postgresql")
    role_urls = {
        "cmh_app": make_url(os.environ["CMH_DATABASE_URL"]),
        "cmh_migrate": make_url(os.environ["CMH_MIGRATE_DATABASE_URL"]),
    }
    with psycopg.connect(administrative.render_as_string(hide_password=False),
                          autocommit=True) as connection:
        for role, url in role_urls.items():
            if url.username != role or not url.password:
                raise RuntimeError("Role initialization URL does not match its role")
            if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
            connection.execute(sql.SQL(
                "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(url.password)))
        for database in ("cmh_v2_dev", "cmh_v2_test"):
            if not connection.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (database,),
            ).fetchone():
                connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    for database in ("cmh_v2_dev", "cmh_v2_test"):
        url = administrative.set(database=database).render_as_string(hide_password=False)
        with psycopg.connect(url, autocommit=True) as connection:
            for extension in ("vector", "ltree", "pgcrypto"):
                connection.execute(sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(
                    sql.Identifier(extension),
                ))
            connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            connection.execute("GRANT USAGE,CREATE ON SCHEMA public TO cmh_migrate")
            connection.execute("GRANT USAGE ON SCHEMA public TO cmh_app")


if __name__ == "__main__":
    initialize()
