"""C0 operator-boundary regressions; no production configuration is consumed."""
import importlib.util
import json
from pathlib import Path

import pytest

from cmh.importing.apply import target_settings

pytestmark = pytest.mark.no_app_operation(
    reason="Operator configuration, pure delta planning and mocked HTTP checks; no app request or service operation.",
)
ROOT = Path(__file__).resolve().parents[2]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "v2" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_C01_production_requires_flag_and_exact_confirmation():
    for flag, name, confirmation in (
        (False, "cmh_v2", "cmh_v2"), (True, "cmh_v2_import", "cmh_v2_import"),
        (True, "cmh_v2", ""), (True, "cmh_v2", "wrong"),
    ):
        with pytest.raises(ValueError):
            target_settings(name, production=flag, confirmation=confirmation, environ={})


def test_C01_production_configuration_never_reads_legacy_or_workspace_prod_secrets(
    configured_env, monkeypatch,
):
    # Deliberately synthetic mapping, never a workspace production secret.
    class Config(dict):
        def __getitem__(self, key):
            assert key == "CMH_PROD_DATABASE_URL"
            return super().__getitem__(key)

    config = Config(CMH_PROD_DATABASE_URL="postgresql://cmh_app:fictional@db/cmh_v2")
    settings = target_settings("cmh_v2", production=True, confirmation="cmh_v2", environ=config)
    assert settings.database_url.get_secret_value().endswith("/cmh_v2")
    config["CMH_PROD_DATABASE_URL"] = "postgresql://cmh_app:fictional@db/other"
    with pytest.raises(ValueError):
        target_settings("cmh_v2", production=True, confirmation="cmh_v2", environ=config)


def test_C02_delta_only_unreviewed_locators_and_attribution(tmp_path):
    from cmh.importing.delta import delta_plan
    from cmh.importing.plan import write_csv

    base = {
        "roster": [{"v1_id": "old", "slug": "agent_nix_test"}],
        "attribution": [{"value": "agent_nix_test"}],
        "namespaces": [{"v1_table": "unstructured_data", "v1_id": "old"}],
    }
    for name, key in (("roster_review.csv", "roster"), ("attribution_review.csv", "attribution"),
                      ("namespace_mapping.csv", "namespaces")):
        write_csv(tmp_path / name, base[key], list(base[key][0]))
    new = {"roster": [*base["roster"], {"v1_id": "new", "slug": "partner_a"}],
           "attribution": [*base["attribution"], {"value": "partner_a"}],
           "namespaces": [*base["namespaces"], {"v1_table": "unstructured_data", "v1_id": "new"}]}
    result = delta_plan(new, tmp_path)
    assert [r["v1_id"] for r in result["roster"]] == ["new"]
    assert [r["value"] for r in result["attribution"]] == ["partner_a"]
    assert [r["v1_id"] for r in result["namespaces"]] == ["new"]


def test_C02_review_checksums_cover_base_and_delta_and_reject_collision(tmp_path):
    import hashlib

    from cmh.importing.delta import approved_reviews
    from cmh.importing.plan import write_csv

    data = {"roster_review.csv": [{"v1_id": "old", "slug": "owner"}],
            "attribution_review.csv": [{"value": "owner", "proposed_principal": "owner"}],
            "namespace_mapping.csv": [{"v1_table": "unstructured_data", "v1_id": "old",
                                       "proposed_namespace": "org"}]}
    data.update({name.replace(".csv", "_delta.csv"): [] for name in list(data)})
    for name, rows in data.items():
        base = name.replace("_delta.csv", ".csv")
        write_csv(tmp_path / name, rows, list(data[base][0]))
    manifest = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in data}
    (tmp_path / "review-file-checksums.json").write_text(json.dumps(manifest))
    result, checksums = approved_reviews(tmp_path)
    assert len(checksums) == 6 and len(result["namespace_mapping.csv"]) == 1
    (tmp_path / "namespace_mapping_delta.csv").write_text("tampered")
    with pytest.raises(ValueError):
        approved_reviews(tmp_path)


def test_C04_export_requires_private_path_and_timezone():
    exporter = script("export_native")
    with pytest.raises(ValueError):
        exporter.validate_export(Path("public/export.json"), "2026-10-13")
    with pytest.raises(ValueError):
        exporter.validate_export(Path(".local/export.json"), "2026-10-13T00:00:00")


def test_CR1_private_export_file_mode_no_email_output_no_overwrite(tmp_path, capsys):
    import stat
    from datetime import UTC, datetime

    exporter = script("export_native")
    path = tmp_path / ".local" / "rollback.json"
    records = {"waitlist": [{"email": "signup@example.invalid"}]}
    counts = {"waitlist": 1}
    exporter.write_export(path, datetime.now(UTC), records, counts)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())["records"] == records
    output = capsys.readouterr()
    assert "signup@example.invalid" not in output.out + output.err
    assert json.loads(output.out) == {"status": "exported", "counts": counts}
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        exporter.write_export(path, datetime.now(UTC), {}, {})
    assert path.read_bytes() == original


def test_CR3_partner_password_random_in_memory_only(tmp_path, capsys, monkeypatch):
    helper = script("partner_accounts")
    generated = []

    def password(size):
        assert size >= 32
        value = "fictional-throwaway-" + str(len(generated))
        generated.append(value)
        return value

    monkeypatch.setattr(helper.secrets, "token_urlsafe", password)
    calls = []

    class Response:
        status_code = 201

        def raise_for_status(self):
            pass

        def json(self):
            return {"principal": {"id": "fictional-id"}}

    class Client:
        def post(self, path, **kwargs):
            calls.append((path, kwargs))
            return Response()

    profile = {"slug": "partner_a", "display_name": "Partner A", "email": "partner@example.invalid"}
    for _ in range(2):
        assert helper.create_partner(Client(), "https://example.invalid", profile) == "fictional-id"
    assert len(set(generated)) == 2
    assert profile == {"slug": "partner_a", "display_name": "Partner A", "email": "partner@example.invalid"}
    for index, (path, kwargs) in enumerate(calls):
        assert path == "/admin/api/principals"
        assert kwargs["headers"] == {"Origin": "https://example.invalid"}
        assert kwargs["json"] == {**profile, "kind": "human", "role": "partner", "tier": 3,
                                  "password": generated[index]}
    assert not capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_C06_only_single_asgi_deployment_and_public_port():
    import tomllib
    config = tomllib.loads((ROOT / "v2/replit-cutover.toml").read_text())
    command = " ".join(config["deployment"]["run"])
    assert "uvicorn" in command and "5000" in command and "start_all.sh" not in command
    assert [(p["localPort"], p["externalPort"]) for p in config["ports"]] == [(5000, 80)]
    current = tomllib.loads((ROOT / ".replit").read_text())
    assert [(p["localPort"], p["externalPort"]) for p in current["ports"]] == [(5000, 80)]
