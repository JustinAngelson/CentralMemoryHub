"""Offline startup safety contracts: no app instance or database connection."""

import ast
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = "postgresql://cmh_app:fictional@ep-example.aws.neon.tech/cmh_v2"
DEVELOPMENT = "postgresql://cmh_app:fictional@localhost/cmh_v2_dev"


def guard():
    from cmh.db.startup import guard_database_target

    return guard_database_target


def test_deployment_marker_allows_production():
    guard()(PRODUCTION, "prod", environ={"REPLIT_DEPLOYMENT": "1"})


@pytest.mark.parametrize("environment", ["dev", "test", "prod"])
def test_workspace_cannot_authorize_production_with_cmh_env(environment):
    with pytest.raises(RuntimeError, match="Production database forbidden"):
        guard()(PRODUCTION, environment, environ={"CMH_PROD_DATABASE_URL": PRODUCTION})


@pytest.mark.parametrize("marker", ["0", "true", "false", "", "unknown"])
def test_unknown_deployment_marker_fails_closed(marker):
    with pytest.raises(RuntimeError, match="Unknown deployment environment"):
        guard()(DEVELOPMENT, "dev", environ={"REPLIT_DEPLOYMENT": marker})


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_workspace_dev_database_allowed(environment):
    guard()(DEVELOPMENT, environment, environ={"CMH_PROD_DATABASE_URL": PRODUCTION})


@pytest.mark.parametrize("target", [
    "postgresql://other:fictional@ep-example.aws.neon.tech/cmh_v2",
    "postgresql://other:fictional@ep-example-pooler.aws.neon.tech/cmh_v2",
    "postgresql://other:fictional@EP-EXAMPLE.aws.neon.tech./cmh_v2",
])
def test_matching_production_target_ignores_credentials_and_pooler(target):
    with pytest.raises(RuntimeError, match="Production database forbidden"):
        guard()(target, "dev", environ={"CMH_PROD_DATABASE_URL": PRODUCTION})


def test_reference_comparison_also_protects_non_neon_target():
    target = "postgresql://cmh_app:fictional@database.example/production"
    reference = "postgresql://other:fictional@database.example/production"
    with pytest.raises(RuntimeError, match="Production database forbidden"):
        guard()(target, "dev", environ={"CMH_PROD_DATABASE_URL": reference})


@pytest.mark.parametrize("target", [
    PRODUCTION,
    "postgresql://cmh_app:fictional@ep-example-pooler.aws.neon.tech/cmh_v2",
])
def test_neon_production_name_refused_without_reference_secret(target):
    with pytest.raises(RuntimeError, match="Production database forbidden"):
        guard()(target, "dev", environ={})


def test_separate_neon_development_database_allowed():
    guard()("postgresql://cmh_app:fictional@ep-dev.aws.neon.tech/cmh_v2_dev",
            "dev", environ={"CMH_PROD_DATABASE_URL": PRODUCTION})


@pytest.mark.parametrize("target", [
    "not-a-database-url",
    "postgresql://cmh_app:fictional@/cmh_v2_dev",
    "postgresql://cmh_app:fictional@localhost/cmh_v2_dev?host=ep-example.aws.neon.tech",
    "postgresql://cmh_app:fictional@localhost/cmh_v2_dev?dbname=cmh_v2",
    "postgresql://cmh_app:fictional@localhost/cmh_v2_dev?service=production",
    "postgresql://cmh_app:fictional@localhost,ep-example.aws.neon.tech/cmh_v2",
])
def test_ambiguous_or_invalid_target_fails_closed_without_url(target):
    with pytest.raises(RuntimeError, match="Invalid database target") as error:
        guard()(target, "dev", environ={})
    assert target not in str(error.value)
    assert "fictional" not in str(error.value)
    assert "postgresql" not in str(error.value)


def test_invalid_reference_fails_closed_without_url():
    with pytest.raises(RuntimeError, match="Invalid production database reference") as error:
        guard()(DEVELOPMENT, "dev", environ={"CMH_PROD_DATABASE_URL": "invalid-reference"})
    assert "invalid-reference" not in str(error.value)


def test_create_app_guards_before_engine_or_embedding_side_effects():
    module = ast.parse((ROOT / "src/cmh/app.py").read_text())
    create = next(n for n in module.body if isinstance(n, ast.FunctionDef)
                  and n.name == "create_app")
    calls = {n.func.id: n.lineno for n in ast.walk(create)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert calls["guard_database_target"] < calls["build_engine"]
    assert calls["guard_database_target"] < calls["configure_logging"]
    assert calls["guard_database_target"] < calls["build_embedding_provider"]


def test_workspace_command_requires_dev_secret_and_venv_only():
    config = tomllib.loads((ROOT / ".replit").read_text())
    workflow = next(w for w in config["workflows"]["workflow"]
                    if w["name"] == "Start application")
    command = next(t["args"] for t in workflow["tasks"] if t["task"] == "shell.exec")
    assert 'CMH_DATABASE_URL="${CMH_DEV_DATABASE_URL:?' in command
    assert "CMH_ENV=dev" in command
    assert ".local/cmh-v2-venv/bin/python -m uvicorn" in command
    # Missing dev configuration must stop the shell before any app invocation.
    result = subprocess.run(["sh", "-c", command], check=False, env={"PATH": "/usr/bin:/bin"},
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert "CMH_DEV_DATABASE_URL" in result.stderr


def test_deployment_commands_and_ports_unchanged():
    config = tomllib.loads((ROOT / ".replit").read_text())
    assert config["deployment"]["run"] == [
        "sh", "-c",
        ("PYTHONPATH=src python -m uvicorn cmh.app:create_app --factory "
         "--host 0.0.0.0 --port 5000 --no-access-log"),
    ]
    assert config["deployment"]["build"] == ["sh", "-c", "python -m pip install ./src/cmh"]
    assert config["ports"] == [{"localPort": 5000, "externalPort": 80}]
