"""Application-construction tests for isolated CI, never the live workspace."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.no_app_operation(reason="Only GET /healthz: unaudited startup guard probe.")
@pytest.mark.parametrize("production", [False, True])
def test_isolated_database_starts_with_known_environment(configured_env, monkeypatch, production):
    from cmh.app import create_app

    monkeypatch.delenv("CMH_PROD_DATABASE_URL", raising=False)
    if production:
        monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
        monkeypatch.setenv("CMH_ENV", "prod")
    else:
        monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
        monkeypatch.setenv("CMH_ENV", "dev")
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.no_app_operation(reason="Startup target guard rejects before any database operation.")
def test_workspace_prod_target_refused_before_connection(configured_env, monkeypatch):
    import cmh.app

    monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
    monkeypatch.setenv("CMH_ENV", "dev")
    monkeypatch.setenv(
        "CMH_DATABASE_URL", "postgresql://cmh_app:fictional@ep-example.aws.neon.tech/cmh_v2",
    )

    def no_engine(*args, **kwargs):
        pytest.fail("Production target reached engine construction")

    monkeypatch.setattr(cmh.app, "build_engine", no_engine)
    with pytest.raises(RuntimeError, match="Production database forbidden"):
        cmh.app.create_app()
