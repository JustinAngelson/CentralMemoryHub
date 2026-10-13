"""Operational imports share service evaluation, explicit filters, RLS and one audit."""
from uuid import uuid4

from sqlalchemy import text

from cmh.importing.shapes import safe_metadata
from cmh.policy.evaluator import evaluate
from cmh.services.entities import encode
from cmh.services.provenance import timestamp


def apply_operational(runner, table, row, locator, path, trace, roster):
    context, engine = runner.context, runner.engine
    if table == "agent_directory":
        selected = next((item for item in roster if item["v1_id"] == locator), None)
        if not selected:
            raise ValueError("Directory source row is absent from reviewed roster")
        if selected["action"] == "skip":
            return "skipped"
        if selected["kind"] == "human":
            return "resolved"
        native_id = runner.by_slug[selected["slug"]]["id"]
        with engine.connect() as conn:
            legacy = conn.execute(text("SELECT legacy_meta FROM agent_directory WHERE principal_id=:id"),
                                  {"id": native_id}).scalar_one()
        if legacy.get("v1_id") == locator:
            return "existing"
    else:
        destination = {"agent_sessions": "sessions", "gpt_messages": "messages",
                       "user_skills": "principal_skill_assignments",
                       "agent_skills": "principal_skill_assignments", "waitlist": "waitlist"}.get(table)
        if not destination:
            raise ValueError("Source table has no approved import disposition")
        with engine.begin() as conn:
            readable = runner.entities.scope(conn, context)
            restriction = "" if table == "waitlist" else "AND namespace_id=ANY(CAST(:readable AS uuid[]))"
            prior = conn.execute(text(f"""SELECT id FROM {destination}
              WHERE legacy_meta->>'v1_table'=:table AND legacy_meta->>'v1_id'=:locator {restriction}"""),
                                 {"table": table, "locator": locator, "readable": readable}).scalar()
        if prior:
            return "existing"

    def change(conn):
        readable = runner.entities.scope(conn, context)
        node = conn.execute(text("SELECT id FROM namespaces WHERE path=CAST(:path AS ltree)"),
                            {"path": path}).scalar_one()
        meta = {"v1_table": table, "v1_id": locator, "imported_at": runner.identity.now().isoformat()}
        clean = safe_metadata(row)
        if table == "agent_directory":
            import json

            reports = row.get("reports_to") or []
            reports = reports if isinstance(reports, list) else [reports]
            unresolved = [value for value in reports
                          if str(value).casefold() not in runner.aliases]
            if unresolved:
                meta["unresolved"] = {"reports_to": unresolved}
            names = {str(item["id"]): slug for slug, item in runner.by_slug.items()}
            reports = [names.get(str(runner.aliases.get(str(value).casefold())), str(value))
                       for value in reports]
            capabilities = row.get("capabilities") or []
            if isinstance(capabilities, dict):
                capabilities = list(capabilities)
            if isinstance(capabilities, str):
                capabilities = [capabilities]
            meta["v1_fields"] = {key: value for key, value in clean.items() if key not in {
                "description", "capabilities", "reports_to", "seniority_level", "agent_id", "name",
            }}
            conn.execute(text("""UPDATE agent_directory SET description=:description,
              capabilities=:capabilities,reports_to_text=:reports,seniority_level=:seniority,
              aliases=:aliases,legacy_meta=CAST(:meta AS jsonb) WHERE principal_id=:id"""), {
                "description": row.get("description"), "capabilities": capabilities,
                "reports": ", ".join(reports), "seniority": row.get("seniority_level"),
                "aliases": list(dict.fromkeys(json.loads(selected["aliases"]))),
                "meta": encode(meta), "id": native_id,
            })
        elif table == "agent_sessions":
            principal = runner.aliases.get(str(row.get("agent_id")).casefold())
            meta["claimed"] = {key: row[key] for key in ("agent_id", "user_id") if row.get(key)}
            started = row.get("started_at") or row.get("start_time") or runner.identity.now()
            tags = row.get("active_context_tags") or []
            tags = tags if isinstance(tags, list) else [tags]
            conn.execute(text("""INSERT INTO sessions(id,principal_id,user_principal_id,namespace_id,
              current_focus,summary_notes,active_context_tags,started_at,ended_at,legacy_meta)
              VALUES(:id,:principal,:user,:node,:focus,:summary,:tags,:started,:ended,CAST(:meta AS jsonb))"""),
                         {"id": uuid4(), "principal": principal,
                          "user": runner.aliases.get(str(row.get("user_id")).casefold()), "node": node,
                          "focus": row.get("current_focus"), "summary": row.get("summary_notes"),
                          "tags": tags, "started": timestamp(started),
                          "ended": timestamp(row["ended_at"]) if row.get("ended_at") else None,
                          "meta": encode(meta)})
        elif table == "gpt_messages":
            sender = runner.aliases.get(str(row.get("sender_agent")).casefold())
            receiver = runner.aliases.get(str(row.get("receiver_agent")).casefold())
            session = conn.execute(text("""SELECT id FROM sessions
              WHERE legacy_meta->>'v1_id'=:id AND namespace_id=ANY(CAST(:readable AS uuid[]))"""),
                                   {"id": str(row.get("session_id")), "readable": readable}).scalar_one_or_none()
            meta["claimed"] = {key: row[key] for key in ("sender_agent", "receiver_agent") if row.get(key)}
            conn.execute(text("""INSERT INTO messages(id,sender_principal_id,receiver_principal_id,
              receiver_text,session_id,namespace_id,message_type,content,created_at,legacy_meta)
              VALUES(:id,:sender,:receiver,:receiver_text,:session,:node,:type,:content,:at,CAST(:meta AS jsonb))"""),
                         {"id": uuid4(), "sender": sender, "receiver": receiver,
                          "receiver_text": None if receiver else row.get("receiver_agent"),
                          "session": session, "node": node, "type": row.get("message_type") or "message",
                          "content": row.get("content") or "", "at": timestamp(row["created_at"])
                          if row.get("created_at") else runner.identity.now(), "meta": encode(meta)})
        elif table in {"agent_skills", "user_skills"}:
            skill = conn.execute(text("""SELECT id,namespace_id FROM entities WHERE kind='skill'
              AND legacy_meta->>'v1_id'=:id AND namespace_id=ANY(CAST(:readable AS uuid[]))"""),
                                 {"id": str(row["skill_id"]), "readable": readable}).mappings().one()
            principal = runner.aliases.get(str(row.get("agent_id") or row.get("user_id")).casefold())
            if not principal:
                raise ValueError("Skill assignment principal is not resolved")
            conn.execute(text("""INSERT INTO principal_skill_assignments(principal_id,skill_entity_id,
              namespace_id,proficiency,legacy_meta) VALUES(:principal,:skill,:node,:proficiency,CAST(:meta AS jsonb))
              ON CONFLICT(principal_id,skill_entity_id) DO NOTHING"""), {
                "principal": principal, "skill": skill["id"], "node": skill["namespace_id"],
                "proficiency": str(row.get("proficiency") or ""), "meta": encode(meta),
            })
        else:
            # Email exists only in this private table, never in legacy_meta, trace or logs.
            conn.execute(text("""INSERT INTO waitlist(email,first_name,company,role,created_at,source,legacy_meta)
              VALUES(:email,:name,:company,:role,:at,'v1_import',CAST(:meta AS jsonb))
              ON CONFLICT(lower(email)) DO NOTHING"""), {
                "email": row["email"].lower(), "name": row.get("first_name"), "company": row.get("company"),
                "role": row.get("role"), "at": timestamp(row["created_at"])
                if row.get("created_at") else runner.identity.now(), "meta": encode(meta),
            })
        return "imported"

    return runner.identity.perform(context, "memory.write", path, change=change,
                                   preflight=lambda conn: {**evaluate(conn, context, "memory.write", path),
                                                           "import": trace},
                                   audit_operation="import." + table)
