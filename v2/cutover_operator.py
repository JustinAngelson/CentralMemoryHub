"""Shared explicit-target bootstrap Owner loader for one-shot operators."""
import argparse
from datetime import UTC, datetime

from sqlalchemy import text

from cmh.auth.context import PrincipalContext
from cmh.db.engine import build_engine
from cmh.importing.apply import target_settings
from cmh.services.core import IdentityService


def arguments(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--database", default="cmh_v2_rehearsal")
    parser.add_argument("--confirm-database")
    return parser


def connect(args):
    confirmation = args.confirm_database
    if args.production and confirmation is None:
        confirmation = input("Type target database name: ")
    settings = target_settings(args.database, production=args.production, confirmation=confirmation)
    engine = build_engine(settings.database_url.get_secret_value())
    with engine.connect() as connection:
        owner = connection.execute(text("""SELECT p.* FROM principals p JOIN bootstrap_state b
          ON b.owner_principal_id=p.id WHERE p.role='owner' AND p.kind='human'""")).mappings().one()
    return engine, IdentityService(engine, lambda: datetime.now(UTC)), PrincipalContext(
        dict(owner), request_meta={"surface": "admin"})
