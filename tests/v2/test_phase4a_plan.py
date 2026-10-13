"""Tests-first review checkpoint. All data/identity defaults are fictional."""
import csv
import importlib
import json
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_app_operation(
    reason="Read-only import planning is not an app operation and must append no audit; no services or request client are called.",
)


def planner():
    return importlib.import_module("cmh.importing.plan")


@pytest.fixture
def defaults():
    return {
        "owner_slug": "owner",
        "rules": [
            {"names": ["Owner Test"], "slug": "owner", "kind": "human", "role": "owner",
             "tier": "", "sponsor": "", "status": "active"},
            {"names": ["Partner Test"], "slug": "partner_a", "kind": "human",
             "role": "partner", "tier": "", "sponsor": "", "status": "active"},
            {"names": ["Agent Runner Test"], "slug": "agent_runner_test", "kind": "agent",
             "role": "", "tier": 2, "sponsor": "partner_a", "status": "active"},
            {"names": ["Agent Historical Test"], "slug": "agent_historical_test",
             "kind": "agent", "role": "", "tier": 1, "sponsor": "owner", "status": "inactive"},
        ],
        "duplicate_names": {"Agent Runner Old": "agent_runner_test"},
        "additions": [{"slug": "agent_routine_test", "name": "Agent Routine Test",
                       "kind": "agent", "role": "", "tier": 2,
                       "sponsor": "owner", "status": "active"}],
        "attribution_aliases": {"owner recorded by runner": "owner",
                               "role title": "agent_runner_test"},
        "attribution_prefixes": {"00000001": "agent_runner_test"},
        "attribution_patterns": [{"pattern": "Agent Runner - *",
                                  "slug": "agent_runner_test"}],
        "unmapped": ["agent_unknown_test"],
    }


@pytest.fixture
def source():
    directory = [
        {"agent_id": "00000000-0000-0000-0000-000000000001", "name": "Owner Test",
         "role": "AI Agent", "status": "active", "seniority_level": 999},
        {"agent_id": "00000000-0000-0000-0000-000000000002", "name": "Partner Test",
         "role": "AI Agent", "status": "active"},
        {"agent_id": "00000001-0000-0000-0000-000000000001", "name": "Agent Runner Test",
         "role": "Owner", "status": "active"},
        {"agent_id": "00000000-0000-0000-0000-000000000003", "name": "Agent Historical Test",
         "status": "active", "seniority_level": 99},
        {"agent_id": "00000000-0000-0000-0000-000000000004", "name": "Agent Persona Test",
         "role": "Superuser", "seniority_level": 999, "status": "active"},
        {"agent_id": "00000000-0000-0000-0000-000000000005", "name": "Agent Runner Old",
         "status": "inactive"},
        {"agent_id": "00000000-0000-0000-0000-000000000006", "name": "",
         "status": "inactive"},
    ]
    return {
        "tables": {
            "agent_directory": directory,
            "unstructured_data": [
                {"id": "memory-one", "content": "Example Mechanical private body [agent: Agent Routine Test]"},
                {"id": "memory-multi", "content": "Example Mechanical and Example Electrical"},
                {"id": "memory-none", "content": "No named client [agent: agent_unknown_test]"},
                {"id": "memory-alias", "content": "Work for 1234567890123456789"},
            ],
            "project_decisions": [
                {"id": "decision-one", "gpt_role": "role title"},
                {"id": "decision-two", "gpt_role": "Agent Runner - Sales"},
                {"id": "decision-three", "gpt_role": "owner recorded by runner"},
            ],
            "gpt_messages": [{"message_id": "message-one", "sender_agent": "agent_unknown_test",
                              "receiver_agent": "Agent Runner Test", "content": "private body"}],
            "shared_contexts": [{"id": "shared-one", "sender": "Owner Test",
                                  "recipients": ["Agent Runner Test", "Agent Historical Test"]}],
            "resources": [{"id": "resource-one", "name": "Resource sample",
                           "url": "https://example.invalid/private-upload",
                           "description": "Example Mechanical"}],
            "skill_files": [{"id": "file-one", "filename": "private-file",
                             "stored_filename": "/private/upload/private-file"}],
        },
        "counts": {"agent_directory": 7, "unstructured_data": 4, "project_decisions": 3,
                   "gpt_messages": 1, "shared_contexts": 1, "resources": 1, "skill_files": 1,
                   "users": 2, "api_keys": 1, "api_request_logs": 3,
                   "invitation_tokens": 1, "waitlist": 2},
    }


@pytest.fixture
def orgs(tmp_path):
    path = tmp_path / "orgs.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "zoho_account_id", "name", "proposed_namespace", "aliases", "notes",
        ])
        writer.writeheader()
        writer.writerows([
            {"zoho_account_id": "1111111111111111111", "name": "Example Mechanical",
             "proposed_namespace": "org.clients.example_mechanical",
             "aliases": "Example Mech; EXM", "notes": "Alias Zoho account ID 1234567890123456789"},
            {"zoho_account_id": "2222222222222222222", "name": "Example Electrical",
             "proposed_namespace": "org.clients.example_electrical"},
            {"zoho_account_id": "3333333333333333333", "name": "Example Company",
             "proposed_namespace": "org"},
            {"zoho_account_id": "4444444444444444444", "name": "Example Mechanical West",
             "proposed_namespace": "org.clients.example_mechanical"},
        ])
    return path


def plan(source, defaults, orgs):
    return planner().build_plan(source, defaults, planner().load_orgs(orgs))


def roster(result, slug):
    return next(r for r in result["roster"] if r["slug"] == slug and r["action"] == "import")


def attribution(result, value):
    return next(r for r in result["attribution"] if r["value"] == value)


def namespace(result, identity):
    return next(r for r in result["namespaces"] if r["v1_id"] == identity)


def test_t4a_1_humans_follow_approved_rules_not_v1_type(source, defaults, orgs):
    result = plan(source, defaults, orgs)
    assert roster(result, "owner")["kind"] == "human"
    assert roster(result, "owner")["role"] == "owner"
    assert roster(result, "partner_a")["role"] == "partner"
    assert roster(result, "owner")["tier"] == 4


def test_t4a_1_active_agent_sponsor_tier_and_no_credentials(source, defaults, orgs):
    row = roster(plan(source, defaults, orgs), "agent_runner_test")
    assert (row["tier"], row["sponsor"], row["status"]) == (2, "partner_a", "active")
    assert "credential" not in row


def test_t4a_1_persona_auth_not_inferred_from_metadata(source, defaults, orgs):
    row = roster(plan(source, defaults, orgs), "agent-persona-test")
    assert (row["tier"], row["sponsor"], row["status"]) == (1, "owner", "inactive")


def test_t4a_1_blank_and_duplicate_skipped_with_aliases(source, defaults, orgs):
    result = plan(source, defaults, orgs)
    skipped = [r for r in result["roster"] if r["action"] == "skip"]
    assert len(skipped) == 2 and all(r["reason"] for r in skipped)
    aliases = json.loads(roster(result, "agent_runner_test")["aliases"])
    assert "Agent Runner Old" in aliases
    assert "00000000-0000-0000-0000-000000000005" in aliases


def test_s4_new_routine_agent_is_active_without_reactivating_historical(source, defaults, orgs):
    result = plan(source, defaults, orgs)
    assert roster(result, "agent_routine_test")["tier"] == 2
    assert roster(result, "agent_routine_test")["status"] == "active"
    assert roster(result, "agent_historical_test")["status"] == "inactive"
    assert len(result["roster"]) == len(source["tables"]["agent_directory"]) + 1


@pytest.mark.parametrize("value,slug", [
    ("role title", "agent_runner_test"),
    ("Agent Runner - Sales", "agent_runner_test"),
    ("owner recorded by runner", "owner"),
    ("00000001-0000-0000-0000-000000000001", "agent_runner_test"),
    ("Agent Routine Test", "agent_routine_test"),
])
def test_s5_attribution_aliases_patterns_ids_and_tags(source, defaults, orgs, value, slug):
    source["tables"]["project_decisions"].append({"id": "extra", "gpt_role": value})
    result = plan(source, defaults, orgs)
    assert attribution(result, value)["proposed_principal"] == slug


def test_s5_unmapped_is_explicit_and_preserved(source, defaults, orgs):
    row = attribution(plan(source, defaults, orgs), "agent_unknown_test")
    assert row["proposed_principal"] == ""
    assert row["review_required"] == "yes" and row["count"] == 2


def test_6_5_client_none_multiple_and_account_alias(source, defaults, orgs):
    result = plan(source, defaults, orgs)
    assert namespace(result, "memory-one")["proposed_namespace"] == "org.clients.example_mechanical"
    assert namespace(result, "memory-multi")["proposed_namespace"] == "org"
    assert namespace(result, "memory-multi")["reason"] == "multiple-client-namespaces"
    assert namespace(result, "memory-none")["reason"] == "no-client-match"
    assert namespace(result, "memory-alias")["proposed_namespace"] == "org.clients.example_mechanical"


def test_s1_aliases_same_parent_are_not_multiple_clients(source, defaults, orgs):
    source["tables"]["unstructured_data"].append({
        "id": "locations", "content": "Example Mechanical and Example Mechanical West",
    })
    assert namespace(plan(source, defaults, orgs), "locations")["proposed_namespace"] == "org.clients.example_mechanical"


def test_namespace_short_alias_has_word_boundaries(source, defaults, orgs):
    source["tables"]["unstructured_data"].append({"id": "boundary", "content": "NOTEXMINSIDE"})
    assert namespace(plan(source, defaults, orgs), "boundary")["proposed_namespace"] == "org"


def test_6_1_preview_accounts_for_excluded_and_waitlist_counts(source, defaults, orgs):
    result = plan(source, defaults, orgs)
    assert result["counts"] == source["counts"]
    assert result["dispositions"]["api_keys"] == "excluded"
    assert result["dispositions"]["waitlist"] == "waitlist"
    assert result["source_total"] == sum(source["counts"].values())


def test_t4a_7_8_review_files_contain_no_content_paths_or_upload_urls(source, defaults, orgs, tmp_path):
    result = plan(source, defaults, orgs)
    planner().write_plan(result, tmp_path)
    for name in ("roster_review.csv", "attribution_review.csv", "namespace_mapping.csv",
                 "reconciliation_preview.md"):
        text = (tmp_path / name).read_text()
        assert "private body" not in text
        assert "/private/upload" not in text
        assert "https://example.invalid/private-upload" not in text
    rows = list(csv.DictReader((tmp_path / "namespace_mapping.csv").open()))
    assert not any("content" in k for r in rows for k in r)


def test_t4a_8_apply_review_guard_requires_all_files(tmp_path):
    for name in ("roster_review.csv", "attribution_review.csv"):
        (tmp_path / name).write_text("header\n")
    with pytest.raises(ValueError, match="review files"):
        planner().require_review_files(tmp_path)


def test_t4a_8_review_guard_checksums_private_not_printed(tmp_path, source, defaults, orgs, capsys):
    planner().write_plan(plan(source, defaults, orgs), tmp_path)
    checksums = planner().require_review_files(tmp_path)
    assert set(checksums) == {"roster_review.csv", "attribution_review.csv", "namespace_mapping.csv"}
    assert all(len(value) == 64 for value in checksums.values())
    assert capsys.readouterr().out == ""


def test_source_guard_rejects_legacy_or_live_databases():
    source_module = importlib.import_module("cmh.importing.source")
    for name in ("heliumdb", "memoryvault", "cmh_v2_dev", "postgres"):
        with pytest.raises(ValueError):
            source_module.validate_snapshot_database(name)


def test_bad_org_namespace_and_conflicting_alias_fail_explicitly(orgs):
    module = planner()
    with orgs.open("a") as handle:
        handle.write('5555555555555555555,Bad,people.owner.private,Example Mech,\n')
    with pytest.raises(ValueError):
        module.load_orgs(orgs)


def test_roster_case_conflicts_fail_instead_of_guessing(source, defaults, orgs):
    defaults["rules"].append({**defaults["rules"][0], "slug": "partner_b"})
    with pytest.raises(ValueError):
        plan(source, defaults, orgs)


def test_safe_csv_formula_cells(tmp_path):
    module = planner()
    module.write_plan({
        "roster": [], "attribution": [{"value": "=fictional_formula", "count": 1,
            "proposed_principal": "", "review_required": "yes", "reason": "unmapped"}],
        "namespaces": [], "counts": {}, "dispositions": {}, "source_total": 0,
    }, tmp_path)
    row = next(csv.DictReader((tmp_path / "attribution_review.csv").open()))
    assert row["value"].startswith("'=")


def test_plan_module_cannot_read_legacy_secret_variables(monkeypatch):
    module = importlib.import_module("cmh.importing.source")
    class Guarded(dict):
        def __getitem__(self, key):
            assert key not in {"DATABASE_URL", "MCP_BEARER_TOKEN", "CMH_V1_READONLY_URL"}
            return super().__getitem__(key)
    monkeypatch.setattr(module.os, "environ", Guarded())
    with pytest.raises(ValueError):
        module.connection_from_env("DATABASE_URL", "cmh_v1_snapshot")


@pytest.fixture(scope="module")
def snapshot_fixture(test_database):
    import psycopg
    from conftest import SensitiveTestValue
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    info = conninfo_to_dict(str(test_database).replace("postgresql+psycopg://", "postgresql://"))
    name = "cmh_v1_fixture_" + uuid.uuid4().hex
    created_role = False
    with psycopg.connect(make_conninfo(**info), autocommit=True) as admin:
        if not admin.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='cmh_v1_reader'",
        ).fetchone():
            admin.execute("CREATE ROLE cmh_v1_reader NOLOGIN")
            admin.execute("ALTER ROLE cmh_v1_reader SET default_transaction_read_only=on")
            created_role = True
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = SensitiveTestValue(make_conninfo(**{**info, "dbname": name}))
    try:
        with psycopg.connect(url, autocommit=True) as admin:
            admin.execute("DROP SCHEMA public")
            schema = Path(__file__).parent / "fixtures" / "v1_schema.sql"
            admin.execute(schema.read_text())
            admin.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            admin.execute("GRANT USAGE ON SCHEMA public TO cmh_v1_reader")
            admin.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO cmh_v1_reader")
            admin.execute("GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO cmh_v1_reader")
            admin.execute("""INSERT INTO public.agent_directory(agent_id,name,role,status)
                VALUES('00000000-0000-0000-0000-000000000001','Owner Test','AI Agent','active')""")
            admin.execute("""INSERT INTO public.unstructured_data(id,content,pinecone_id)
                VALUES('memory-one','Example Mechanical [agent: Owner Test]','fake-vector')""")
        yield url
    finally:
        with psycopg.connect(make_conninfo(**info), autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
            if created_role:
                admin.execute("DROP ROLE cmh_v1_reader")


def test_t4a_6_source_uses_reader_and_read_only(snapshot_fixture):
    module = importlib.import_module("cmh.importing.source")
    with module.source_connection(snapshot_fixture) as conn:
        values = conn.execute("SELECT current_user AS name,current_setting('transaction_read_only') AS mode").fetchone()
        assert values == {"name": "cmh_v1_reader", "mode": "on"}


def test_t4a_6_write_through_source_fails_25006(snapshot_fixture):
    import psycopg

    module = importlib.import_module("cmh.importing.source")
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction), module.source_connection(snapshot_fixture) as conn:
        conn.execute("INSERT INTO public.unstructured_data(id,content) VALUES('never-stored','fictional')")


def test_t4a_6_unreachable_legacy_urls_not_read(snapshot_fixture, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unreachable.invalid/never")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "fictional-canary")
    module = importlib.import_module("cmh.importing.source")
    snapshot = module.read_source(snapshot_fixture)
    assert len(snapshot["counts"]) == 24
    assert "api_keys" not in snapshot["tables"]
    assert "waitlist" not in snapshot["tables"]
    assert snapshot["counts"]["unstructured_data"] == 1


def test_t4a_8_target_counts_and_audit_unchanged(snapshot_fixture, test_database, defaults, orgs, tmp_path):
    module = importlib.import_module("cmh.importing.source")
    before = module.target_state(test_database)
    minimal = {**defaults, "rules": defaults["rules"][:1], "additions": [],
               "attribution_aliases": {}, "attribution_prefixes": {}, "attribution_patterns": []}
    result = planner().build_plan(module.read_source(snapshot_fixture), minimal, planner().load_orgs(orgs))
    planner().write_plan(result, tmp_path)
    assert module.target_state(test_database) == before


def test_t4a_6_remote_snapshot_url_refused_before_connect(monkeypatch):
    module = importlib.import_module("cmh.importing.source")
    monkeypatch.setenv("CMH_V1_SNAPSHOT_URL", "postgresql://reader@unreachable.invalid/cmh_v1_snapshot")
    with pytest.raises(ValueError, match="isolated local"):
        module.connection_from_env("CMH_V1_SNAPSHOT_URL", "cmh_v1_snapshot")


def test_t4a_8_whole_target_metadata_can_use_isolated_admin_env(monkeypatch):
    from psycopg.conninfo import conninfo_to_dict

    module = importlib.import_module("cmh.importing.source")
    monkeypatch.setenv("CMH_TEST_DATABASE_URL", "postgresql://test_admin@localhost/cmh_v2_test")
    info = conninfo_to_dict(module.connection_from_env("CMH_TEST_DATABASE_URL", "cmh_v2_import"))
    assert info["dbname"] == "cmh_v2_import" and info["user"] == "test_admin"


def test_t4a_8_snapshot_secret_cannot_be_used_as_target_env(monkeypatch):
    module = importlib.import_module("cmh.importing.source")
    monkeypatch.setenv("CMH_V1_SNAPSHOT_URL", "postgresql://reader@localhost/cmh_v1_snapshot")
    with pytest.raises(ValueError):
        module.connection_from_env("CMH_V1_SNAPSHOT_URL", "cmh_v2_import")


def test_cli_refuses_public_review_output_directory(tmp_path):
    import runpy

    cli = runpy.run_path(str(Path(__file__).parents[2] / "v2" / "import_v1.py"))
    with pytest.raises(ValueError, match="private"):
        cli["private_output_directory"](tmp_path / "public")


def test_cli_accepts_private_review_output_directory(tmp_path):
    import runpy

    cli = runpy.run_path(str(Path(__file__).parents[2] / "v2" / "import_v1.py"))
    directory = tmp_path / ".local" / "cmh-v2-import"
    assert cli["private_output_directory"](directory) == directory.resolve()


@pytest.mark.parametrize("alias", ["EXM", "XYZ", "ZX", "FIC"])
def test_short_alias_case_sensitive_whole_words(alias):
    module = importlib.import_module("cmh.importing.namespaces")
    org = [{"namespace": "org.clients.example", "aliases": [alias]}]
    rows = module.make_namespaces({"unstructured_data": [
        {"id": "exact", "content": f"Work {alias} today"},
        {"id": "lower", "content": f"Work {alias.lower()} today"},
        {"id": "embedded", "content": f"prefix{alias}suffix"},
    ]}, org, {})
    assert [x["proposed_namespace"] for x in rows] == ["org.clients.example", "org", "org"]
