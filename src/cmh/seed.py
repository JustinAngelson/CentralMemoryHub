"""Explicit idempotent seeds; never run automatically in migrations or startup."""

import json
from pathlib import Path

from sqlalchemy import text

from cmh.config import load_settings
from cmh.db.engine import build_engine


def seed_database(engine):
    # Explicit CLI convention: run from the repository/container root. Works
    # both with the source tree and the installed wheel.
    directory = Path.cwd() / "seed"
    with engine.begin() as connection:
        for item in json.loads((directory / "namespaces.yaml").read_text()):
            connection.execute(text("""
              INSERT INTO namespaces(path,mode,governed)
              VALUES(CAST(:path AS ltree),:mode,:governed) ON CONFLICT(path) DO NOTHING
            """), item)
        for item in json.loads((directory / "templates.yaml").read_text()):
            connection.execute(text("""
              INSERT INTO credential_templates
              (name,target_role,target_tier,scopes,namespace_grants_template,
               default_expiry_days,requires_owner_approval)
              VALUES(:name,:role,:tier,:scopes,CAST(:grants AS jsonb),:days,:approval)
              ON CONFLICT(name) DO NOTHING
            """), {**item, "grants": json.dumps(item["grants"])})
        if connection.execute(text("SELECT to_regclass('public.edge_types')")).scalar():
            for item in json.loads((directory / "edge_types.yaml").read_text()):
                connection.execute(text("""
                  INSERT INTO edge_types(type,allowed_src_kinds,allowed_dst_kinds,mirrored)
                  VALUES(:type,:src,:dst,:mirrored) ON CONFLICT(type) DO NOTHING
                """), item)


def main():
    settings = load_settings()
    engine = build_engine(settings.database_url.get_secret_value())
    try:
        seed_database(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
