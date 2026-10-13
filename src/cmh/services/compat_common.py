"""Compatibility mapping helpers; never imports or queries the v1 application."""

from uuid import UUID

from sqlalchemy import text

SELF = {"gpt_role", "made_by_agent", "created_by_agent", "sender_agent", "sender",
        "last_updated_by", "agent_id"}
TARGETS = {"assigned_to_agent", "receiver_agent", "recipients", "owner_agent",
           "executing_agent", "used_by_agents", "user_id"}
KIND_TABLE = {
    "memory": "unstructured_data", "decision": "decision_log", "knowledge": "kb_index",
    "org_state": "org_state", "task": "agent_tasks", "experiment": "experiments",
    "insight": "user_insights", "shared_context": "shared_contexts",
    "memory_link": "memory_links",
}
KINDS = {
    "store_structured": "memory", "get_structured": "memory",
    "store_knowledge": "knowledge", "search_knowledge": "knowledge",
    "log_decision": "decision", "list_decisions": "decision",
    "create_org_state": "org_state", "update_org_state": "org_state",
    "list_org_states": "org_state", "create_task": "task", "update_task": "task",
    "list_tasks": "task", "create_experiment": "experiment", "list_experiments": "experiment",
    "log_user_insight": "insight", "list_user_insights": "insight",
    "share_context": "shared_context", "list_contexts": "shared_context",
    "create_memory_link": "memory_link", "list_memory_links": "memory_link",
}


def resolve(conn, value):
    if not isinstance(value, str) or not value:
        return None
    return conn.execute(text("""
      SELECT p.* FROM principals p LEFT JOIN agent_directory d ON d.principal_id=p.id
      WHERE lower(p.slug)=lower(:value) OR lower(p.display_name)=lower(:value)
        OR EXISTS(SELECT 1 FROM unnest(d.aliases) alias WHERE lower(alias)=lower(:value))
        OR p.id::text=lower(:value)
      ORDER BY CASE WHEN lower(p.slug)=lower(:value) THEN 0
                    WHEN lower(p.display_name)=lower(:value) THEN 1
                    WHEN p.id::text=lower(:value) THEN 3 ELSE 2 END,p.id LIMIT 1
    """), {"value": value}).mappings().first()


def claims(conn, context, payload, meta=None):
    meta = dict(meta or {})
    claimed = dict(meta.get("claimed", {}))
    current_claims = {key: payload[key] for key in SELF if key in payload}
    claimed.update(current_claims)
    meta["claimed"] = claimed
    meta["v1_fields"] = {**meta.get("v1_fields", {}), **payload}
    # Self fields in returned legacy views describe the real principal, not a claim.
    meta["v1_fields"].update({key: context.principal["slug"] for key in SELF if key in payload})
    meta["claimed_identity_mismatch"] = False
    for value in current_claims.values():
        principal = resolve(conn, value)
        if value and (not principal or str(principal["id"]) != str(context.id)):
            meta["claimed_identity_mismatch"] = True
    resolved, unresolved = dict(meta.get("resolved", {})), dict(meta.get("unresolved", {}))
    for field in TARGETS & payload.keys():
        value = payload[field]
        values = value if isinstance(value, list) else [value]
        found = [resolve(conn, item) for item in values]
        resolved[field] = [str(item["id"]) if item else None for item in found]
        if any(item is None and raw for item, raw in zip(found, values)):
            unresolved[field] = value
        else:
            unresolved.pop(field, None)
        canonical = [item["slug"] if item else raw for item, raw in zip(found, values)]
        meta["v1_fields"][field] = canonical if isinstance(value, list) else canonical[0]
    meta.update(resolved=resolved, unresolved=unresolved)
    return meta


def principal_id(meta, field):
    return next(iter(meta.get("resolved", {}).get(field, [])), None)


def old_identity(value, table):
    try:
        UUID(str(value))
        return str(value)
    except ValueError:
        return str(value) if str(value).startswith("v1:") else f"v1:{table}:{value}"


def priority(value, previous=None, creating=False):
    if value is None:
        return previous
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(
        value.lower(), 2 if creating else previous,
    )
