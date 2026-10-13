"""Phase 2A kind registry. Skills/resources/assignments belong to Phase 4A."""

TYPED = {
    "memory": ("memories", {"content": "text"}),
    "decision": ("decisions", {
        "decision_text": "text", "rationale": "text", "context": "text",
        "impact_area": "text", "reversal_possible": "boolean",
    }),
    "knowledge": ("knowledge", {
        "term": "text", "definition": "text", "synonyms": "text[]",
        "defined_by_file": "text", "used_by_principal_ids": "uuid[]",
        "relevance_score": "integer", "last_verified": "timestamptz",
    }),
    "org_state": ("org_states", {"state_key": "text", "state": "jsonb"}),
    "task": ("tasks", {
        "title": "text", "description": "text", "task_status": "text",
        "assignee_principal_id": "uuid REFERENCES principals(id)", "due_at": "timestamptz",
        "priority": "integer", "linked_project": "text", "summary_notes": "text",
    }),
    "experiment": ("experiments", {
        "title": "text", "description": "text", "hypothesis": "text", "outcome": "text",
        "notes": "text", "experiment_status": "text",
        "executing_principal_id": "uuid REFERENCES principals(id)",
    }),
    "insight": ("insights", {
        "subject_principal_id": "uuid REFERENCES principals(id)", "interaction_type": "text",
        "summary": "text", "related_agent_or_project": "text", "result": "text", "tone_tag": "text",
    }),
    "shared_context": ("shared_contexts", {
        "recipient_principal_ids": "uuid[]", "context_tag": "text", "memory_ref_entity_ids": "uuid[]",
    }),
    "inbox_item": ("inbox_items", {
        "content": "text", "submitted_by_external_id": "uuid REFERENCES principals(id)",
    }),
    "memory_link": ("memory_links", {
        "summary": "text", "linked_event_ref": "text", "linked_session_id": "uuid",
        "linked_message_id": "uuid", "origin_file_or_source": "text",
    }),
    "org": ("orgs", {
        "name": "text", "vertical": "text", "org_type": "text", "is_active": "boolean",
        "website": "text",
    }),
    "engagement": ("engagements", {
        "name": "text", "engagement_type": "text", "lane": "text", "capability_pillar": "text",
        "engagement_status": "text", "health": "text", "start_date": "date",
        "target_completion": "date", "actual_completion": "date", "outcome_summary": "text",
        "fuse_tier": "integer", "fuse_cycle_number": "integer", "fuse_outcomes": "jsonb",
    }),
    "project": ("projects", {
        "name": "text", "project_status": "text", "offer_lane": "text", "current_mode": "text",
        "active_workstreams": "text[]", "summary": "text", "success_criteria": "text",
    }),
    "note": ("notes", {"body": "text", "note_title": "text"}),
}
MIRRORED = {"org", "engagement", "project", "note"}
NATIVE = set(TYPED) - MIRRORED
DEFAULT_KINDS = sorted(set(TYPED) - {"memory_link"})
RESOURCE = {
    "decision": "decisions", "knowledge": "knowledge", "org_state": "orgstate",
    "task": "tasks", "experiment": "experiments", "insight": "insights",
    "inbox_item": "inbox",
    **dict.fromkeys(MIRRORED, "entities"),
}


def operation(kind, write=False):
    return RESOURCE.get(kind, "memory") + (".write" if write else ".read")
