"""Exercise real v1 routes/models against an isolated in-memory database."""
import importlib
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SESSION_SECRET", "test-only-session-secret")
    monkeypatch.delenv("WAITLIST_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("CMH_PUBLIC_URL", raising=False)
    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.delenv("CMH_TRUSTED_PROXY_HOPS", raising=False)
    # Pinecone performs network operations at import; none belong in this suite.
    monkeypatch.setitem(sys.modules, "pinecone_client", types.ModuleType("pinecone_client"))
    application = importlib.import_module("app")
    routes = importlib.import_module("routes")
    models = importlib.import_module("models")
    application.app.config.update(TESTING=True)
    with application.app.app_context():
        tables = [models.Waitlist.__table__, models.GPTMessage.__table__]
        application.db.metadata.create_all(application.db.engine, tables=tables)
        routes.rate_limiter.request_counts.clear()
        if hasattr(routes, "waitlist_rate_limiter"):
            routes.waitlist_rate_limiter.request_counts.clear()
        yield application.app, application.db, routes, models
        application.db.session.remove()
        application.db.metadata.drop_all(application.db.engine, tables=tables)


@pytest.fixture
def client(runtime):
    return runtime[0].test_client()
