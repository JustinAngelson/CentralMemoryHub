"""Legacy entity CRUD: context attribution, one kernel write, scoped list projection."""

import json
import re

from sqlalchemy import text

from cmh import audit
from cmh.kernel import operation
from cmh.policy.evaluator import deny, evaluate, namespace
from cmh.services.compat_common import (
    KIND_TABLE,
    KINDS,
    TARGETS,
    claims,
    old_identity,
    principal_id,
    priority,
    resolve,
)
from cmh.services.provenance import provenance, timestamp


class CompatEntities:
    def __init__(self, entities, operations):
        self.entities = entities
        self.identity = entities.identity
        self.operations = operations

    def call(self, context, name, payload):
        action = name.removeprefix("cmh_")
        kind = KINDS[action]
        if action.startswith(("store_", "create_", "log_")) or action == "share_context":
            return self.create(context, kind, action, payload)
        if action.startswith("update_"):
            return self.update(context, kind, payload)
        return self.read(context, kind, action, payload)

    def create(self, context, kind, action, payload):
        path = payload.get("namespace") or "org"
        op = operation(kind, True)
        if not isinstance(path, str) or not re.fullmatch(r"[\w-]+(?:\.[\w-]+)*", path):
            return self.identity.record(context, deny("NAMESPACE_FORBIDDEN", 5), op)
        with self.entities.engine.connect() as conn:
            meta = claims(conn, context, payload)
            result = evaluate(conn, context, op, path)
            if meta.get("claimed_identity_mismatch"):
                result = {**result, "claimed_identity_mismatch": True}
        if result["outcome"] != "ALLOW":
            return self.identity.record(context, result, op, path)
        content = next((payload[field] for field in (
            "content", "decision_text", "summary", "term", "title", "context_tag", "entity",
        ) if isinstance(payload.get(field), str)), "")
        values, prov_meta, invalid = provenance(
            context, {**payload, "content": content}, self.entities.now(), True,
        )
        if invalid:
            return self.identity.record(context, invalid, op, path)
        meta.update({key: value for key, value in prov_meta.items() if key != "claimed"})
        meta["claimed"].update(prov_meta["claimed"])
        meta["original_table"] = "project_decisions" if action == "store_structured" else (
            KIND_TABLE[kind]
        )
        try:
            data = self.data(kind, payload, meta)
        except (ValueError, TypeError):
            return self.identity.record(context, {
                **deny("VALIDATION_FAILED", 7),
                **({"claimed_identity_mismatch": True}
                   if meta.get("claimed_identity_mismatch") else {}),
            }, op, path)
        about = None
        if kind == "shared_context":
            with self.entities.engine.begin() as conn:
                readable = self.entities.scope(conn, context)
                refs = [self.entities.find(conn, readable, str(ref),
                                          self.entities.kinds(context, ["memory"]))
                        for ref in payload["memory_refs"]]
                data["memory_ref_entity_ids"] = [str(row["id"]) for row in refs if row]
                unresolved = [raw for raw, row in zip(payload["memory_refs"], refs) if not row]
                if unresolved:
                    meta["unresolved"]["memory_refs"] = unresolved
        if kind == "memory_link":
            with self.entities.engine.begin() as conn:
                readable = self.entities.scope(conn, context)
                target = self.entities.find(conn, readable, str(payload["pinecone_vector_id"]),
                                            self.entities.kinds(context, ["memory"]))
                if not target:
                    target = conn.execute(text("""
                      SELECT * FROM entities
                      WHERE namespace_id=ANY(CAST(:readable AS uuid[])) AND kind='memory'
                        AND legacy_meta->>'pinecone_id'=:archive
                    """), {"readable": readable, "archive": payload["pinecone_vector_id"]}
                    ).mappings().first() if self.entities.kinds(context, ["memory"]) else None
                if not target:
                    return self.identity.record(
                        context, deny("EDGE_ENDPOINT_FORBIDDEN", 5), op, path,
                    )
                about = str(target["id"])
                for table, column in (("sessions", "linked_session_id"),
                                      ("messages", "linked_message_id")):
                    linked = self.operations.find(
                        conn, readable, table, payload.get("linked_agent_event"),
                    ) if evaluate(conn, context, "messages.read")["outcome"] == "ALLOW" else None
                    if linked:
                        data[column] = linked["id"]
                        break
        return self.entities.create(context, kind, data, values, path, legacy_meta=meta, about=about)

    def data(self, kind, payload, meta, current=None):
        if kind == "memory":
            return {"content": payload["decision_text"]}
        if kind == "decision":
            return {key: payload[key] for key in (
                "decision_text", "context", "impact_area", "reversal_possible",
            ) if key in payload}
        if kind == "knowledge":
            data = {key: payload[key] for key in (
                "term", "defined_by_file", "relevance_score", "synonyms",
            ) if key in payload}
            data["used_by_principal_ids"] = [
                item for item in meta.get("resolved", {}).get("used_by_agents", []) if item
            ]
            return data
        if kind == "org_state":
            state = dict((current or {}).get("state", {}))
            state.update(meta["v1_fields"])
            if "owner_agent" in payload:
                state["owner_principal_id"] = principal_id(meta, "owner_agent")
            return {"state_key": payload.get("entity", (current or {}).get("state_key")),
                    "state": state}
        if kind == "task":
            data = {key: payload[key] for key in (
                "title", "description", "linked_project", "summary_notes",
            ) if key in payload}
            if "status" in payload:
                data["task_status"] = payload["status"]
            if "assigned_to_agent" in payload:
                data["assignee_principal_id"] = principal_id(meta, "assigned_to_agent")
            if "due_date" in payload:
                data["due_at"] = timestamp(payload["due_date"]) if payload["due_date"] else None
            if "priority" in payload:
                data["priority"] = priority(payload["priority"],
                                            (current or {}).get("priority"), current is None)
            return data
        if kind == "experiment":
            return {**{key: payload[key] for key in (
                "title", "description", "hypothesis", "outcome", "notes",
            ) if key in payload}, "experiment_status": payload.get("status"),
                    "executing_principal_id": principal_id(meta, "executing_agent")}
        if kind == "insight":
            return {**{key: payload[key] for key in (
                "summary", "interaction_type", "related_agent_or_project", "result", "tone_tag",
            ) if key in payload}, "subject_principal_id": principal_id(meta, "user_id")}
        if kind == "shared_context":
            return {"context_tag": payload["context_tag"],
                    "recipient_principal_ids": [
                        item for item in meta.get("resolved", {}).get("recipients", []) if item
                    ], "memory_ref_entity_ids": []}
        return {key: payload.get(key) for key in (
            "summary", "origin_file_or_source",
        )} | {"linked_event_ref": payload.get("linked_agent_event")}

    def update(self, context, kind, payload):
        payload = {key: value for key, value in payload.items() if value is not None}
        op = operation(kind, True)
        identity = old_identity(payload.get("task_id", payload.get("entity_id")), KIND_TABLE[kind])
        with self.entities.engine.begin() as conn:
            readable = self.entities.scope(conn, context)
            row = self.entities.find(conn, readable, identity, [kind])
            if row:
                path = conn.execute(text("SELECT path::text FROM namespaces WHERE id=:id"),
                                    {"id": row["namespace_id"]}).scalar_one()
                result = evaluate(conn, context, op, path)
                if result["outcome"] == "ALLOW":
                    snapshot = self.entities.snapshot(conn, row, readable)
                    meta = claims(conn, context, payload, row["legacy_meta"])
                    try:
                        data = self.data(kind, payload, meta, snapshot)
                    except (ValueError, TypeError):
                        result = deny("VALIDATION_FAILED", 7)
            else:
                # Authorization before existence; read-scoped target lookup never leaks.
                result = evaluate(conn, context, op, payload.get("namespace", "org"))
                if result["outcome"] == "ALLOW":
                    result = deny("NOT_FOUND")
        if result["outcome"] != "ALLOW":
            return self.identity.record(context, result, op)
        return self.entities.update(context, str(row["id"]), data, expected_kind=kind,
                                    legacy_meta=meta)

    def read(self, context, kind, action, payload):
        op = operation(kind)
        path = payload.get("namespace")
        result = None
        with self.entities.engine.begin() as conn:
            result = evaluate(conn, context, op, path)
            if result["outcome"] == "ALLOW":
                if action.startswith("search_"):
                    self.entities.embedding_ready()
                readable = self.entities.scope(conn, context)
                node = namespace(conn, path) if path else None
                if action == "get_structured":
                    row = self.entities.find(conn, readable, old_identity(
                        payload["id"], "project_decisions",
                    ), ["memory"])
                    snapshots = [self.entities.snapshot(conn, row, readable)] if row else []
                    snapshots = [item for item in snapshots if item["legacy_meta"].get(
                        "original_table",
                    ) == "project_decisions"]
                else:
                    records = conn.execute(text("""
                      SELECT * FROM entities WHERE kind=:kind AND status='canonical'
                        AND namespace_id=ANY(CAST(:readable AS uuid[]))
                        AND (CAST(:ns AS uuid) IS NULL OR namespace_id=CAST(:ns AS uuid))
                      ORDER BY created_at DESC,id
                    """), {"kind": kind, "readable": readable,
                           "ns": node["id"] if node else None}).mappings()
                    snapshots = [self.entities.snapshot(conn, dict(row), readable) for row in records]
                for snapshot in snapshots:
                    snapshot["author_slug"] = conn.execute(text(
                        "SELECT slug FROM principals WHERE id=:id"
                    ), {"id": snapshot["author_principal_id"]}).scalar()
                try:
                    snapshots = self.filter(conn, snapshots, payload)
                except (TypeError, ValueError):
                    result = deny("VALIDATION_FAILED", 7)
                if result["outcome"] == "ALLOW":
                    if action == "get_structured" and not snapshots:
                        result = deny("NOT_FOUND")
                    else:
                        audit.append(conn, context, result, op, self.entities.now(), path,
                                     resource_type=kind,
                                     resource_id=snapshots[0]["id"] if action == "get_structured"
                                     else None)
                        return snapshots[0] if action == "get_structured" else snapshots
        return self.identity.record(context, result, op, path)

    def filter(self, conn, snapshots, payload):
        from cmh.mcp.compat_formats import project

        output = []
        for snapshot in snapshots:
            view = project(snapshot)
            matches = True
            for field, value in payload.items():
                if value is None or field in ("namespace", "as_of", "limit", "id"):
                    continue
                if field in ("from_date", "to_date"):
                    bound = timestamp(value)
                    at = snapshot["occurred_at"]
                    matches &= at >= bound if field == "from_date" else at <= bound
                elif field == "min_relevance":
                    matches &= view.get("relevance_score") is not None and (
                        view["relevance_score"] >= value
                    )
                elif field == "term":
                    matches &= value.lower() in (view.get("term") or "").lower() or (
                        value.lower() in json.dumps(view.get("synonyms") or []).lower()
                    )
                elif field in TARGETS or field in ("made_by_agent", "created_by_agent", "agent"):
                    target = resolve(conn, value)
                    canonical = target["slug"] if target else value
                    actual = view.get("used_by_agents") if field == "agent" else view.get(field)
                    matches &= canonical.lower() in [
                        str(item).lower() for item in (actual if isinstance(actual, list) else [actual])
                    ]
                elif field in view:
                    matches &= str(view[field]).lower() == str(value).lower()
            if matches:
                output.append(snapshot)
        return output
