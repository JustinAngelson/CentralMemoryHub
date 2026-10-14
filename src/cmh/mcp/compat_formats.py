"""Literal v1 success formats; no extra prose, JSON envelopes or provider calls."""

import json


def iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def project(row):
    meta = row.get("legacy_meta", {})
    fields = meta.get("v1_fields", {})
    targets = row.get("target_slugs", {})
    unresolved = meta.get("unresolved", {})
    kind = row["kind"]
    base = {"created_at": iso(row["created_at"]), "updated_at": iso(row["updated_at"])}
    author = row.get("author_slug") or fields.get("gpt_role") or fields.get("made_by_agent")
    if kind == "memory":
        return {"id": str(row["id"]), "gpt_role": author, "decision_text": row["content"],
                "context_embedding": fields.get("context_embedding",
                                               meta.get("context_embedding")),
                "related_documents": fields.get("related_documents", []),
                "timestamp": iso(row["occurred_at"])}
    if kind == "decision":
        return {"decision_id": str(row["id"]), "context": row.get("context"),
                "made_by_agent": author,
                "timestamp": iso(row["occurred_at"]), "decision_text": row["decision_text"],
                "impact_area": row.get("impact_area"),
                "reversal_possible": row.get("reversal_possible")}
    if kind == "knowledge":
        return {**base, "index_id": str(row["id"]), "term": row["term"],
                "defined_by_file": row.get("defined_by_file"),
                "used_by_agents": targets.get("used_by_agents", []) or unresolved.get(
                    "used_by_agents", [],
                ),
                "relevance_score": row.get("relevance_score"),
                "last_verified": iso(row.get("last_verified")), "synonyms": row.get("synonyms")}
    if kind == "org_state":
        state = row["state"]
        return {**base, "entity_id": str(row["id"]),
                **{key: state.get(key) for key in (
                    "entity", "type", "status", "summary", "owner_agent",
                    "last_updated_by", "important_dates", "linked_docs",
                 )}, "owner_agent": targets.get("owner_agent") or unresolved.get(
                     "owner_agent",
                 ) or state.get("owner_agent")}
    if kind == "task":
        return {**base, "task_id": str(row["id"]), "title": row["title"],
                "description": row.get("description"),
                "assigned_to_agent": targets.get("assigned_to_agent") or unresolved.get(
                    "assigned_to_agent",
                ), "created_by_agent": author,
                "status": row.get("task_status"), "priority": row.get("priority"),
                "linked_project": row.get("linked_project"), "summary_notes": row.get("summary_notes"),
                "due_date": iso(row.get("due_at"))}
    if kind == "experiment":
        return {**base, "experiment_id": str(row["id"]),
                **{key: row.get(key) for key in (
                    "title", "description", "hypothesis", "outcome", "notes",
                )}, "executing_agent": targets.get("executing_agent") or unresolved.get(
                    "executing_agent",
                ),
                "status": row.get("experiment_status")}
    if kind == "insight":
        return {"insight_id": str(row["id"]), "user_id": targets.get("user_id") or unresolved.get(
            "user_id",
        ),
                **{key: row.get(key) for key in (
                    "interaction_type", "summary", "related_agent_or_project", "result", "tone_tag",
                )}, "timestamp": iso(row["occurred_at"])}
    if kind == "shared_context":
        return {"id": str(row["id"]), "sender": author,
                "recipients": targets.get("recipients", []) or unresolved.get("recipients", []),
                "context_tag": row["context_tag"],
                "memory_refs": [str(item) for item in (
                    row.get("memory_ref_entity_ids") or []
                )] + unresolved.get("memory_refs", []),
                "timestamp": iso(row["occurred_at"])}
    return {"link_id": str(row["id"]), "pinecone_vector_id": row.get(
                "edge_target_display", row.get("edge_target"),
            ),
            "summary": row.get("summary"), "linked_agent_event": row.get("linked_event_ref"),
            "origin_file_or_source": row.get("origin_file_or_source"),
            "timestamp_added": iso(row["created_at"])}


EMPTY = {
    "cmh_list_contexts": "No shared contexts found.",
    "cmh_list_org_states": "No org states found matching your filters.",
    "cmh_list_decisions": "No decisions found matching your filters.",
    "cmh_search_knowledge": "No knowledge terms found matching your query.",
    "cmh_list_memory_links": "No memory links found matching your filters.",
    "cmh_list_sessions": "No sessions found matching your filters.",
    "cmh_list_messages": "No messages found matching filters.",
    "cmh_list_tasks": "No tasks found matching your filters.",
    "cmh_list_experiments": "No experiments found matching your filters.",
    "cmh_list_user_insights": "No user insights found matching your filters.",
}


def operational(row):
    if "principal_id" in row:
        return {"session_id": str(row["id"]),
                **{key: iso(row.get(key)) for key in (
                    "agent_id", "started_at", "ended_at", "user_id", "current_focus",
                    "summary_notes", "active_context_tags",
                )}}
    return {"message_id": str(row["id"]), "sender_agent": row.get("sender_agent"),
            "receiver_agent": row.get("receiver_agent"), "timestamp": iso(row["created_at"]),
            "message_type": row["message_type"], "content": row["content"],
            "session_id": str(row["session_id"]) if row["session_id"] else None}


def directory(rows):
    if not rows:
        return "No agents registered in the directory."
    entries = [{
        "agent_id": str(row["id"]), "name": row["display_name"],
        "role": row["legacy_meta"].get("role", row["role"]),
        "description": row["description"], "capabilities": row["capabilities"],
        "skills": [], "skill_ids": [], "usual_model": row["legacy_meta"].get("usual_model"),
        "agent_type": row["legacy_meta"].get("agent_type"),
        "reports_to": row["reports_to_text"], "seniority_level": row["seniority_level"],
        "status": row["status"], "join_date": row["legacy_meta"].get("join_date"),
        "birth_date": row["legacy_meta"].get("birth_date"),
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row.get("updated_at") or row["legacy_meta"].get("updated_at")),
        "subordinate_count": 0, "subordinates": [], "tier": row["tier"],
        "sponsor_slug": row["sponsor_slug"],
    } for row in rows]
    by_id = {item["agent_id"]: item for item in entries}
    names = {str(value).lower(): str(row["id"]) for row in rows
             for value in (row["id"], row["slug"], row["display_name"], *row["aliases"])}
    parents = {item["agent_id"]: names.get(str(item["reports_to"]).lower()) for item in entries}
    roots = []
    for item in entries:
        parent = parents[item["agent_id"]]
        visited = {item["agent_id"]}
        ancestor = parent
        while ancestor and ancestor not in visited:
            visited.add(ancestor)
            ancestor = parents.get(ancestor)
        if parent and not ancestor:
            by_id[parent]["subordinates"].append(item)
            by_id[parent]["subordinate_count"] += 1
        else:
            roots.append(item)
    active = [row for row in entries if row["status"] == "active"]
    inactive = [row for row in entries if row["status"] != "active"]
    lines = [f"AGENT ROSTER ({len(entries)} total, {len(active)} active)\n", "Active agents:"]
    for row in active:
        manager = by_id[parents[row["agent_id"]]]["name"] if parents[row["agent_id"]] else None
        lines.append(f"  • {row['name']} | {row['role']}" +
                     (f" → reports to {manager}" if manager else " (top-level)"))
    if inactive:
        lines.append("\nInactive agents:")
        lines.extend(f"  • {row['name']} | {row['role']}" for row in inactive)
    lines.extend(["\n\nFULL ORG CHART (JSON):", json.dumps(roots, indent=2)])
    return "\n".join(lines)


def format_success(name, body):
    if name == "cmh_list_agents":
        return directory(body)
    if name == "cmh_health_check":
        return json.dumps(body, indent=2)
    if name.startswith(("cmh_list_", "cmh_search_")):
        if not body:
            return EMPTY[name]
        return json.dumps([operational(row) if name in (
            "cmh_list_sessions", "cmh_list_messages",
        ) else project(row) for row in body], indent=2, default=str)
    if name == "cmh_get_structured":
        return json.dumps(project(body), indent=2, default=str)
    if name == "cmh_end_session" and body.get("_already_ended"):
        return f"Session already ended at: {iso(body['ended_at'])}"
    value = operational(body) if name in (
        "cmh_create_session", "cmh_end_session", "cmh_send_message",
    ) else project(body)
    if name == "cmh_create_memory_link":
        value["pinecone_vector_id"] = body["_requested_pinecone_vector_id"]
    formats = {
        "cmh_store_structured": "Structured memory stored successfully.\nID: {id}",
        "cmh_store_knowledge": "Knowledge term stored.\nIndex ID: {index_id}\nTerm: {term}",
        "cmh_log_decision": "Decision logged.\nDecision ID: {decision_id}\nMade by: "
                            "{made_by_agent}\nReversible: {reversal_possible}",
        "cmh_create_org_state": "Org state created.\nEntity ID: {entity_id}\nEntity: "
                                "{entity}\nStatus: {status}",
        "cmh_update_org_state": "Org state updated.\nEntity: {entity}\nStatus: {status}",
        "cmh_create_task": "Task created.\nTask ID: {task_id}\nTitle: {title}\nAssigned to: "
                           "{assigned_to_agent}\nStatus: {status}",
        "cmh_update_task": "Task updated.\nTask ID: {task_id}\nTitle: {title}\nStatus: "
                           "{status}\nAssigned to: {assigned_to_agent}",
        "cmh_create_experiment": "Experiment created.\nExperiment ID: {experiment_id}\n"
                                 "Title: {title}\nStatus: {status}",
        "cmh_log_user_insight": "User insight logged.\nInsight ID: {insight_id}\nUser: "
                                "{user_id}\nType: {interaction_type}",
        "cmh_share_context": "Context shared successfully.\nID: {id}\nTag: {context_tag}\n"
                             "Recipients: {recipient_text}",
        "cmh_create_memory_link": "Memory link created.\nLink ID: {link_id}\n"
                                  "Pinecone ID: {pinecone_vector_id}",
        "cmh_create_session": "Session created.\nSession ID: {session_id}\nAgent ID: {agent_id}",
        "cmh_end_session": "Session ended.\nSession ID: {session_id}\nEnded at: {ended_at}",
        "cmh_send_message": "Message logged.\nMessage ID: {message_id}\nFrom: {sender_agent}"
                            " → {receiver_text}",
    }
    if name == "cmh_share_context":
        value["recipient_text"] = ", ".join(value["recipients"])
    if name == "cmh_send_message":
        value["receiver_text"] = value["receiver_agent"] or "broadcast"
    return formats[name].format(**value)
