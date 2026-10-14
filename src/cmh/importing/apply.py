"""Local-only operator apply entry point. Bootstrap/native users must exist beforehand."""
import json
import os

from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr
from sqlalchemy import URL, text

from cmh.auth.context import PrincipalContext
from cmh.config import load_settings
from cmh.db.engine import build_engine
from cmh.importing.embedding import ImportEmbeddingProvider
from cmh.importing.namespaces import alias_hit_counts, load_orgs
from cmh.importing.runner import ImportRunner
from cmh.importing.source import connection_from_env, read_source
from cmh.services.core import IdentityService
from cmh.services.embedding import build_embedding_provider
from cmh.services.entities import EntityService


def target_settings(database, *, production=False, confirmation=None, environ=None):
    if production:
        if database != "cmh_v2" or confirmation != database:
            raise ValueError("Production requires typed confirmation of cmh_v2")
        env = os.environ if environ is None else environ
        values = conninfo_to_dict(env["CMH_PROD_DATABASE_URL"].replace(
            "postgresql+psycopg://", "postgresql://"))
        if values.get("dbname") != "cmh_v2" or values.get("user") != "cmh_app":
            raise ValueError("Production requires cmh_app on cmh_v2")
    else:
        values = conninfo_to_dict(connection_from_env("CMH_DATABASE_URL", database))
    settings = load_settings()
    address = URL.create("postgresql+psycopg", username=values["user"], password=values.get("password"),
                         host=values.get("host"), port=int(values.get("port", 5432)), database=database,
                         query={key: values[key] for key in ("sslmode",) if key in values})
    return settings.model_copy(update={"database_url": SecretStr(address.render_as_string(hide_password=False))})


def apply_reviewed(source_url, database, directory, *, production=False, confirmation=None):
    from cmh.importing.delta import approved_reviews

    approved_reviews(directory)
    settings = target_settings(database, production=production, confirmation=confirmation)
    engine = build_engine(settings.database_url.get_secret_value())
    try:
        from datetime import UTC, datetime

        with engine.connect() as conn:
            native = conn.execute(text("""SELECT p.* FROM principals p JOIN bootstrap_state b
              ON p.id=b.owner_principal_id WHERE p.role='owner'""")).mappings().one()
        owner = PrincipalContext(dict(native), request_meta={"surface": "import"})
        identity = IdentityService(engine, lambda: datetime.now(UTC))
        provider = ImportEmbeddingProvider(build_embedding_provider(settings))
        if provider.model == "deterministic-test-v1":
            raise ValueError("Operator apply requires real embeddings, not the fake test provider")
        entities = EntityService(identity, provider, settings.embedding_retry_seconds)
        runner = ImportRunner(entities, owner)
        source = read_source(source_url, include_waitlist=True)
        result = runner.apply(source, directory)
        result["alias_hit_counts"] = alias_hit_counts(source["tables"], load_orgs(directory / "orgs.csv"))
        result["alias_hit_count_definition"] = "case-sensitive whole-word occurrences for length <=3"
        result["embedding_calls"] = provider.calls
        result["chunked_records"] = provider.chunked_records
        output = directory / "apply-report.json"
        output.write_text(json.dumps(result, indent=2, default=str))
        output.chmod(0o600)
        return result
    finally:
        engine.dispose()
