"""Phase 4A Step 0: R8/R9 regressions before importer or preflight work."""

import json
from uuid import uuid4

import pytest
from test_phase2_compat import body, compat_case  # noqa: F401
from test_phase2_kernel import context


@pytest.fixture
def link_target(request):
    case, ids = request.getfixturevalue("compat_case")
    case.tamper("""
      UPDATE entities SET legacy_meta=legacy_meta ||
        '{"v1_table":"unstructured_data","v1_id":"fixture-memory-12",
          "pinecone_id":"archived-fixture-vector"}'::jsonb WHERE id=:id
    """, id=ids["memory"])
    return case, ids


def target_name(ids, form):
    return {"uuid": ids["memory"], "v1id": "fixture-memory-12",
            "prefixed": "v1:unstructured_data:fixture-memory-12",
            "archive": "archived-fixture-vector"}[form]


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["uuid", "v1id", "prefixed", "archive"])
async def test_R8_create_echoes_the_exact_requested_identifier(link_target, form):
    case, ids = link_target
    requested = target_name(ids, form)
    async with case.mcp(case.agent_a["credential"]) as session:
        result = await session.call_tool("cmh_create_memory_link", {"params": {
            "pinecone_vector_id": requested, "namespace": case.namespace,
        }})
    assert not result.isError
    assert body(result).splitlines()[-1] == "Pinecone ID: " + requested


@pytest.mark.asyncio
@pytest.mark.parametrize("form", ["uuid", "v1id", "prefixed", "archive"])
async def test_R8_filter_resolves_about_target_and_lists_archived_identifier(link_target, form):
    case, ids = link_target
    other = case.app.state.memory_service.store(context(case), {
        "content": "unrelated fixture memory", "namespace": case.namespace,
    })
    async with case.mcp(case.agent_a["credential"]) as session:
        for target in (ids["memory"], str(other["id"])):
            result = await session.call_tool("cmh_create_memory_link", {"params": {
                "pinecone_vector_id": target, "namespace": case.namespace,
            }})
            assert not result.isError
        result = await session.call_tool("cmh_list_memory_links", {"params": {
            "pinecone_vector_id": target_name(ids, form), "namespace": case.namespace,
        }})
    assert not result.isError
    listed = json.loads(body(result))
    assert len(listed) == 1
    assert listed[0]["pinecone_vector_id"] == "archived-fixture-vector"


@pytest.mark.asyncio
async def test_R8_unarchived_target_lists_v2_uuid_and_unknown_filter_matches_nothing(identity):
    case = identity
    memory = case.app.state.memory_service.store(context(case), {
        "content": "plain fixture memory", "namespace": case.namespace,
    })
    async with case.mcp(case.agent_a["credential"]) as session:
        await session.call_tool("cmh_create_memory_link", {"params": {
            "pinecone_vector_id": str(memory["id"]), "namespace": case.namespace,
        }})
        found = await session.call_tool("cmh_list_memory_links", {"params": {
            "pinecone_vector_id": str(memory["id"]), "namespace": case.namespace,
        }})
        absent = await session.call_tool("cmh_list_memory_links", {"params": {
            "pinecone_vector_id": "missing-fixture-vector", "namespace": case.namespace,
        }})
    assert json.loads(body(found))[0]["pinecone_vector_id"] == str(memory["id"])
    assert body(absent) == "No memory links found matching your filters."


@pytest.mark.asyncio
@pytest.mark.parametrize("filter_form", ["slug", "display"])
async def test_R9_display_owner_projects_slug_and_filters_by_either_identity(identity, filter_form):
    case = identity
    display = "Agent Nix Test " + uuid4().hex
    owner = case.agent_b["principal"]
    case.tamper("UPDATE principals SET display_name=:name WHERE id=:id",
                name=display, id=owner["id"])
    async with case.mcp(case.agent_a["credential"]) as session:
        created = await session.call_tool("cmh_create_org_state", {"params": {
            "entity": "Example Mechanical", "type": "project", "status": "active",
            "owner_agent": display, "namespace": case.namespace,
        }})
        assert not created.isError
        result = await session.call_tool("cmh_list_org_states", {"params": {
            "owner_agent": owner["slug"] if filter_form == "slug" else display,
            "namespace": case.namespace,
        }})
    assert not result.isError
    listed = json.loads(body(result))
    assert len(listed) == 1
    assert listed[0]["owner_agent"] == owner["slug"]


@pytest.mark.asyncio
async def test_R9_unresolved_owner_preserves_raw_text_and_filter(identity):
    case = identity
    async with case.mcp(case.agent_a["credential"]) as session:
        await session.call_tool("cmh_create_org_state", {"params": {
            "entity": "Example Mechanical", "type": "project", "status": "active",
            "owner_agent": "Unmapped Fixture Agent", "namespace": case.namespace,
        }})
        result = await session.call_tool("cmh_list_org_states", {"params": {
            "owner_agent": "Unmapped Fixture Agent", "namespace": case.namespace,
        }})
    assert json.loads(body(result))[0]["owner_agent"] == "Unmapped Fixture Agent"


@pytest.mark.asyncio
async def test_R9_update_replaces_resolved_owner_and_old_filter_no_longer_matches(identity):
    case = identity
    display = "Agent Partner Test " + uuid4().hex
    owner = case.agent_b["principal"]
    case.tamper("UPDATE principals SET display_name=:name WHERE id=:id",
                name=display, id=owner["id"])
    async with case.mcp(case.agent_a["credential"]) as session:
        result = await session.call_tool("cmh_create_org_state", {"params": {
            "entity": "Example Mechanical", "type": "project", "status": "active",
            "owner_agent": "Unmapped Fixture Agent", "namespace": case.namespace,
        }})
        state_id = body(result).splitlines()[1].removeprefix("Entity ID: ")
        updated = await session.call_tool("cmh_update_org_state", {"params": {
            "entity_id": state_id, "owner_agent": display,
        }})
        assert not updated.isError
        old = await session.call_tool("cmh_list_org_states", {"params": {
            "owner_agent": "Unmapped Fixture Agent", "namespace": case.namespace,
        }})
        found = await session.call_tool("cmh_list_org_states", {"params": {
            "owner_agent": owner["slug"], "namespace": case.namespace,
        }})
    assert body(old) == "No org states found matching your filters."
    assert json.loads(body(found))[0]["owner_agent"] == owner["slug"]
