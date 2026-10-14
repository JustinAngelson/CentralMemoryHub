"""Tripwires for the private development transport; no external v2 port."""

import shlex
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.no_app_operation(reason="Static .replit ports tripwire only.")
def test_replit_ports_are_v1_only():
    config = tomllib.loads((ROOT / ".replit").read_text())
    assert config.get("ports") == [{"localPort": 5000, "externalPort": 80}]


@pytest.mark.no_app_operation(reason="Static Unix-socket command and workflow inspection only.")
def test_dev_transport_uses_unix_socket_without_port_wait():
    command = shlex.split((ROOT / "v2/dev.sh").read_text().replace("\\\n", " "))
    assert command[command.index("--uds") + 1] == ".local/cmh-v2.sock"
    assert "--host" not in command
    assert "--port" not in command
    config = tomllib.loads((ROOT / ".replit").read_text())
    workflows = [
        item for item in config["workflows"]["workflow"] if item["name"] == "v2 dev"
    ]
    for workflow in workflows:
        assert all("waitForPort" not in task for task in workflow["tasks"])


def test_health_smoke_alias(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == client.get("/healthz").json()
