"""The container must include only its application inputs, including seeds."""

from pathlib import Path

import pytest


@pytest.mark.no_app_operation(reason="Container packaging guard; inspects build inputs only.")
def test_container_allowlist_includes_seed_and_role_initializer():
    root = Path(__file__).resolve().parents[2]
    rules = (root / ".dockerignore").read_text().splitlines()
    assert rules[0] == "*"
    assert "!seed/" in rules and "!seed/**" in rules
    assert "!v2/init_database.py" in rules
    for name in ("namespaces", "bundles", "templates"):
        assert (root / "seed" / (name + ".yaml")).is_file()
    assert (root / "v2" / "init_database.py").is_file()
    assert not any(rule.startswith("!.local") for rule in rules)
