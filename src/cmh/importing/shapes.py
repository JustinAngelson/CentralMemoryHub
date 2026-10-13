"""Pure v1-to-native shapes; file locations and credential fields have no typed home."""
import re
from pathlib import PurePosixPath

from cmh.kernel import TYPED
from cmh.services.provenance import SOURCE_CONFIDENCE, parse_tags, timestamp

KINDS = {"unstructured_data": "memory", "project_decisions": "memory",
         "decision_log": "decision", "kb_index": "knowledge", "org_profile": "org_state",
         "org_state": "org_state", "agent_tasks": "task", "experiments": "experiment",
         "user_insights": "insight", "shared_contexts": "shared_context",
         "memory_links": "memory_link", "skills": "skill", "resources": "resource",
         "skill_files": "resource"}
ACTOR_FIELDS = {"gpt_role", "made_by_agent", "created_by_agent", "owner_agent",
                "created_by", "sender_agent", "agent_id", "last_updated_by"}
UNSAFE_FIELDS = {"password", "password_hash", "email", "api_key", "token", "stored_filename",
                 "stored_path", "file_path", "path", "url", "file_bytes", "file_content"}
RENAMES = {
    "decision": {"decision": "decision_text"},
    "knowledge": {"keyword": "term", "description": "definition"},
    "task": {"task_name": "title", "task_description": "description", "status": "task_status"},
    "experiment": {"experiment_name": "title", "status": "experiment_status"},
    "org_state": {"key": "state_key", "value": "state"},
    "resource": {"type": "resource_type"},
    "skill": {"skill_name": "name", "skill_description": "description"},
}
REFERENCES = {"assigned_to_agent": "assignee_principal_id",
              "executing_agent": "executing_principal_id", "user_id": "subject_principal_id"}


def safe_metadata(row):
    result = {}
    for key, value in row.items():
        if key in UNSAFE_FIELDS:
            continue
        if key == "filename" and isinstance(value, str):
            value = PurePosixPath(value.replace("\\", "/")).name
        if isinstance(value, str) and ("/uploads/" in value or "\\uploads\\" in value):
            continue
        result[key] = value
    return result


def shape(table, row, locator, aliases, attribution, now):
    kind = KINDS[table]
    columns = TYPED[kind][1]
    cleaned = safe_metadata(row)
    data, consumed = {}, set()
    for key, value in cleaned.items():
        target = RENAMES.get(kind, {}).get(key, key)
        if target in columns:
            data[target] = value
            consumed.add(key)
        if key in REFERENCES and REFERENCES[key] in columns:
            data[REFERENCES[key]] = aliases.get(str(value).casefold())
            consumed.add(key)
    if kind == "memory":
        data = {"content": str(row.get("content") or row.get("decision_text") or row.get("decision") or "")}
        consumed |= {"content", "decision_text", "decision"}
    if table == "org_profile":
        data = {"state_key": "org_profile", "state": cleaned}
        consumed = set(cleaned)
    if table == "skill_files":
        data = {"name": cleaned.get("filename", "Skill file"), "resource_type": "skill_file",
                "metadata": {"filename": cleaned.get("filename"), "skill_id": row.get("skill_id")}}
        consumed |= {"filename", "skill_id"}
    if kind == "resource":
        data.setdefault("metadata", {})
    if kind == "skill":
        data.setdefault("configuration", {})
    if kind == "knowledge" and isinstance(data.get("synonyms"), str):
        data["synonyms"] = [data["synonyms"]]
    if kind == "task":
        for key in ("due_at",):
            if data.get(key):
                data[key] = timestamp(data[key])
    for key in list(data):
        definition = columns[key]
        if definition.startswith("uuid") and data[key] is not None and key not in REFERENCES.values():
            values = data[key] if isinstance(data[key], list) else [data[key]]
            resolved = [aliases.get(str(value).casefold()) for value in values]
            data[key] = [value for value in resolved if value] if "[]" in definition else resolved[0]
    content = row.get("content") or row.get("decision_text") or ""
    tags, original = parse_tags(content)
    claimed = {key: row[key] for key in ACTOR_FIELDS if row.get(key)}
    if "agent" in tags:
        claimed["agent"] = tags["agent"]
    actor = tags.get("agent") or next((row.get(key) for key in (
        "gpt_role", "made_by_agent", "created_by_agent", "created_by", "owner_agent",
    ) if row.get(key)), None)
    author = attribution.get(str(actor).casefold()) if actor else None
    created = timestamp(row["created_at"]) if row.get("created_at") else now
    updated = timestamp(row["updated_at"]) if row.get("updated_at") else created
    occurred = created
    meta = {"v1_table": table, "v1_id": locator, "imported_at": now.isoformat(),
            "claimed": claimed}
    if "date" not in tags or "source" not in tags:
        meta["provenance_defaulted"] = True
    if not row.get("created_at") and table == "unstructured_data":
        meta["occurred_at_unknown"] = True
    if original:
        meta["original_tags"] = original
    if "date" in tags:
        try:
            occurred = timestamp(tags["date"])
            meta.pop("occurred_at_unknown", None)
        except (ValueError, TypeError):
            meta["unparsed_tags"] = re.findall(r"\[date:[^\]]+\]", original)
            meta["provenance_defaulted"] = True
    source_type, confidence = SOURCE_CONFIDENCE.get(tags.get("source"), ("legacy_v1", 0.70))
    if tags.get("source") and tags["source"] not in SOURCE_CONFIDENCE:
        meta.setdefault("unparsed_tags", []).extend(re.findall(r"\[source:[^\]]+\]", original))
        meta["provenance_defaulted"] = True
    if row.get("pinecone_id"):
        meta["pinecone_id"] = row["pinecone_id"]
    if row.get("context_embedding") is not None:
        meta["context_embedding"] = row["context_embedding"]
    if table == "project_decisions":
        meta["original_table"] = table
    consumed |= ACTOR_FIELDS | {"id", "created_at", "updated_at", "pinecone_id", "context_embedding"}
    remaining = {key: value for key, value in cleaned.items() if key not in consumed}
    if remaining:
        meta["v1_fields"] = remaining
    return {"kind": kind, "data": data, "legacy_meta": meta, "author": author,
            "created_at": created, "updated_at": updated,
            "title": row.get("title") or row.get("name"),
            "provenance": {"source_type": source_type, "source_ref": None,
                           "confidence": confidence, "occurred_at": occurred}}
