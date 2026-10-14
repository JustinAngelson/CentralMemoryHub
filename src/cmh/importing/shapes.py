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
                "created_by", "sender_agent", "sender", "agent_id", "last_updated_by"}
TIME_FIELDS = {"created_at", "updated_at", "timestamp", "timestamp_added", "uploaded_at",
               "last_verified", "due_date", "due_at"}
CREATED_FIELDS = {"decision_log": "timestamp", "project_decisions": "timestamp",
                  "shared_contexts": "timestamp", "user_insights": "timestamp",
                  "memory_links": "timestamp_added", "skill_files": "uploaded_at",
                  "org_profile": "updated_at"}
UNSAFE_FIELDS = {"password", "password_hash", "email", "api_key", "token", "stored_filename",
                 "stored_path", "file_path", "path", "url", "file_bytes", "file_content"}
RENAMES = {
    "decision": {"decision": "decision_text"},
    "knowledge": {"keyword": "term", "description": "definition"},
    "task": {"task_name": "title", "task_description": "description", "status": "task_status",
             "due_date": "due_at"},
    "experiment": {"experiment_name": "title", "status": "experiment_status"},
    "org_state": {"key": "state_key", "value": "state"},
    "resource": {"type": "resource_type"},
    "memory_link": {"linked_agent_event": "linked_event_ref"},
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
        data = {"state_key": "org_profile", "state": {
            key: value for key, value in cleaned.items() if key not in TIME_FIELDS}}
        consumed = set(cleaned)
    if table == "org_state":
        data = {"state_key": row["entity"], "state": {
            key: row[key] for key in ("entity", "type", "status", "summary", "owner_agent",
                                     "last_updated_by", "important_dates", "linked_docs")
            if key in row}}
        consumed |= set(data["state"])
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
    for key in ("due_at", "last_verified"):
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
        "gpt_role", "made_by_agent", "created_by_agent", "sender", "created_by",
        "last_updated_by", "owner_agent",
    ) if row.get(key)), None)
    author = attribution.get(str(actor).casefold()) if actor else None
    source_time = row.get(CREATED_FIELDS.get(table, "created_at"))
    created = timestamp(source_time) if source_time else now
    updated = timestamp(row["updated_at"]) if row.get("updated_at") else created
    occurred = created
    meta = {"v1_table": table, "v1_id": locator, "imported_at": now.isoformat(),
            "claimed": claimed}
    for field, column in {"recipients": "recipient_principal_ids",
                          "used_by_agents": "used_by_principal_ids",
                          "owner_agent": None, **REFERENCES}.items():
        if field not in row:
            continue
        raw = row[field]
        values = raw if isinstance(raw, list) else [raw]
        resolved = [aliases.get(str(value).casefold()) for value in values]
        meta.setdefault("resolved", {})[field] = resolved
        missing = [value for value, found in zip(values, resolved) if not found]
        if missing:
            meta.setdefault("unresolved", {})[field] = missing if isinstance(raw, list) else raw
        if column:
            data[column] = ([value for value in resolved if value]
                            if "[]" in columns[column] else resolved[0])
        consumed.add(field)
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
    consumed |= ACTOR_FIELDS | TIME_FIELDS | {"id", "pinecone_id", "context_embedding"}
    remaining = {key: value for key, value in cleaned.items() if key not in consumed}
    if remaining:
        meta["v1_fields"] = remaining
    return {"kind": kind, "data": data, "legacy_meta": meta, "author": author,
            "created_at": created, "updated_at": updated,
            "title": row.get("title") or row.get("name"),
            "provenance": {"source_type": source_type, "source_ref": None,
                           "confidence": confidence, "occurred_at": occurred}}
