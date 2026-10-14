"""Alembic alone uses CMH_MIGRATE_DATABASE_URL; no runtime/v1 fallback."""

import os

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.exc import ArgumentError

from cmh.db.engine import normalize_database_url

url = os.environ.get("CMH_MIGRATE_DATABASE_URL")
if not url:
    raise RuntimeError("CMH_MIGRATE_DATABASE_URL is required for migrations")
try:
    connection_url = normalize_database_url(url)
except (ArgumentError, TypeError, ValueError):
    raise RuntimeError("Invalid CMH_MIGRATE_DATABASE_URL for migrations") from None

if context.is_offline_mode():
    context.configure(url=connection_url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(
        connection_url, connect_args={"connect_timeout": 3}, hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
