"""Application-construction tests for isolated CI, never the live workspace."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(params=[False, True], ids=["development", "deployment"])
def isolated_startup_client(configured_env, monkeypatch, request):
    from cmh.app import create_app

    monkeypatch.delenv("CMH_PROD_DATABASE_URL", raising=False)
    if request.param:
        monkeypatch.setenv("REPLIT_DEPLOYMENT", "1")
        monkeypatch.setenv("CMH_ENV", "prod")
    else:
        monkeypatch.delenv("REPLIT_DEPLOYMENT", raising=False)
        monkeypatch.setenv("CMH_ENV", "dev")
    with TestClient(create_app()) as client:
        yield client, "prod" if request.param else "dev"


@pytest.mark.no_app_operation(reason="Only GET /healthz: unaudited startup guard probe.")
def test_isolated_database_starts_with_known_environment(isolated_startup_client):
    client, expected_environment = isolated_startup_client
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["env"] == expected_environment


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
