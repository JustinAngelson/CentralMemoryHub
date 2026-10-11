"""V2 database URLs and test isolation. No production or v1 fallback."""

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import sessionmaker


def normalize_database_url(value: str):
    url = make_url(value)
    if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg"):
        raise ValueError("CMH requires a PostgreSQL URL")
    return url.set(drivername="postgresql+psycopg")


class TestDatabaseIsolationError(RuntimeError):
    __test__ = False


def _database_identity(value: str):
    url = normalize_database_url(value)
    host = (url.host or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        host = "loopback"
    return host, url.port or 5432, url.database, url.query.get("host")


def guard_test_database(test_url: str, dev_url: str | None, v1_url: str | None) -> None:
    try:
        if not test_url:
            raise ValueError
        identity = _database_identity(test_url)
        if not identity[2] or any(
            identity == _database_identity(other) for other in (dev_url, v1_url) if other
        ):
            raise ValueError
    except (ArgumentError, TypeError, ValueError):
        raise TestDatabaseIsolationError(
            "Unsafe CMH_TEST_DATABASE_URL: missing, invalid, or targets a non-test database"
        ) from None


def build_engine(url: str):
    return create_engine(
        normalize_database_url(url), pool_pre_ping=True,
        connect_args={"connect_timeout": 2}, echo=False, hide_parameters=True,
    )


def build_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
