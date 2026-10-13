"""Operational session/message/directory calls with explicit filters and atomic audit."""

from uuid import UUID, uuid4

from sqlalchemy import text

from cmh import audit
from cmh.policy.evaluator import deny, evaluate, namespace
from cmh.services.compat_common import claims, principal_id, resolve
from cmh.services.entities import encode


class CompatOperations:
    def __init__(self, entities):
        self.entities = entities
        self.identity = entities.identity

    def find(self, conn, readable, table, identity):
        if not identity:
            return None
        try:
            uuid = UUID(str(identity))
        except ValueError:
            uuid = None
        old_table = "agent_sessions" if table == "sessions" else "gpt_messages"
        old_id = str(identity)
        if old_id.startswith("v1:"):
            parts = old_id.split(":", 2)
            if len(parts) != 3 or parts[1] != old_table:
                return None
            old_id = parts[2]
        return conn.execute(text(f"""
          SELECT * FROM {table} WHERE namespace_id=ANY(CAST(:readable AS uuid[]))
            AND (id=:uuid OR (legacy_meta->>'v1_table'=:table
                             AND legacy_meta->>'v1_id'=:legacy))
          ORDER BY (id=:uuid) DESC NULLS LAST LIMIT 1
        """), {"readable": readable, "uuid": uuid, "table": old_table, "legacy": old_id}
        ).mappings().first()

    def call(self, context, name, payload):
        write = name in ("cmh_create_session", "cmh_end_session", "cmh_send_message")
        op = "messages.write" if write else "messages.read"
        if name == "cmh_list_agents":
            op = "directory.read"
        path = payload.get("namespace") or ("org" if write else None)
        result = None
        with self.entities.engine.begin() as conn:
            meta = claims(conn, context, payload)
            result = evaluate(conn, context, op, path)
            if result["outcome"] == "ALLOW":
                readable = self.entities.scope(conn, context)
                if meta.get("claimed_identity_mismatch"):
                    result = {**result, "claimed_identity_mismatch": True}
                if write and not self.entities.embedding_ready():
                    result = deny("READ_ONLY_MODE")
            if result["outcome"] == "ALLOW":
                node = namespace(conn, path) if path else None
                row = None
                if name == "cmh_create_session":
                    row = dict(conn.execute(text("""
                      INSERT INTO sessions(id,principal_id,user_principal_id,namespace_id,
                        current_focus,summary_notes,active_context_tags,started_at,legacy_meta)
                      VALUES(:id,:principal,:user,:ns,:focus,:notes,:tags,:now,CAST(:meta AS jsonb))
                      RETURNING *
                    """), {"id": uuid4(), "principal": context.id,
                           "user": principal_id(meta, "user_id"), "ns": node["id"],
                           "focus": payload.get("current_focus"), "notes": payload.get("summary_notes"),
                           "tags": payload.get("active_context_tags"), "now": self.entities.now(),
                           "meta": encode(meta)}).mappings().one())
                elif name in ("cmh_end_session", "cmh_send_message"):
                    session = self.find(conn, readable, "sessions", payload["session_id"]) if (
                        evaluate(conn, context, "messages.read")["outcome"] == "ALLOW"
                    ) else None
                    if not session:
                        result = deny("NOT_FOUND")
                    elif name == "cmh_end_session":
                        session_path = conn.execute(text(
                            "SELECT path::text FROM namespaces WHERE id=:id"
                        ), {"id": session["namespace_id"]}).scalar_one()
                        result = evaluate(conn, context, op, session_path)
                        if result["outcome"] == "ALLOW":
                            row = dict(conn.execute(text("""
                              UPDATE sessions SET ended_at=coalesce(ended_at,:now)
                              WHERE id=:id AND namespace_id=ANY(CAST(:readable AS uuid[]))
                              RETURNING *
                            """), {"id": session["id"], "now": self.entities.now(),
                                   "readable": readable}).mappings().one())
                            row["_already_ended"] = session["ended_at"] is not None
                    else:
                        row = dict(conn.execute(text("""
                          INSERT INTO messages(id,sender_principal_id,receiver_principal_id,
                            receiver_text,session_id,namespace_id,message_type,content,
                            created_at,legacy_meta)
                          VALUES(:id,:sender,:receiver,:text,:session,:ns,:type,:content,
                            :now,CAST(:meta AS jsonb)) RETURNING *
                        """), {"id": uuid4(), "sender": context.id,
                               "receiver": principal_id(meta, "receiver_agent"),
                               "text": payload.get("receiver_agent"), "session": session["id"],
                               "ns": node["id"], "type": payload["message_type"],
                               "content": payload["content"], "now": self.entities.now(),
                               "meta": encode(meta)}).mappings().one())
                elif name == "cmh_list_agents":
                    row = [dict(item) for item in conn.execute(text("""
                      SELECT p.*,d.description,d.capabilities,d.reports_to_text,
                        d.seniority_level,d.aliases,d.legacy_meta,s.slug AS sponsor_slug
                      FROM agent_directory d JOIN principals p ON p.id=d.principal_id
                      LEFT JOIN principals s ON s.id=p.sponsor_id
                      WHERE p.kind='agent' ORDER BY d.seniority_level DESC NULLS LAST,p.slug
                    """)).mappings()]
                else:
                    table = "sessions" if name == "cmh_list_sessions" else "messages"
                    records = conn.execute(text(f"""
                      SELECT * FROM {table} WHERE namespace_id=ANY(CAST(:readable AS uuid[]))
                        AND (CAST(:ns AS uuid) IS NULL OR namespace_id=CAST(:ns AS uuid))
                      ORDER BY {"started_at" if table == "sessions" else "created_at"} DESC,id
                    """), {"readable": readable, "ns": node["id"] if node else None}).mappings()
                    row = [self.enrich(conn, dict(item)) for item in records]
                    row = [item for item in row if self.matches(conn, item, payload, readable)]
                if result["outcome"] == "ALLOW":
                    if isinstance(row, dict):
                        row = self.enrich(conn, row)
                    audit.append(conn, context, result, op, self.entities.now(), path,
                                 resource_type="session" if "session" in name else "message",
                                 resource_id=row["id"] if isinstance(row, dict) else None)
                    return row
        if meta.get("claimed_identity_mismatch"):
            result = {**result, "claimed_identity_mismatch": True}
        return self.identity.record(context, result, op, path)

    def enrich(self, conn, row):
        for source, destination in (("sender_principal_id", "sender_agent"),
                                    ("receiver_principal_id", "receiver_agent"),
                                    ("user_principal_id", "user_id")):
            if source in row:
                row[destination] = conn.execute(text("SELECT slug FROM principals WHERE id=:id"),
                                                {"id": row[source]}).scalar() if row[source] else (
                    row["legacy_meta"].get("v1_fields", {}).get(destination)
                )
        if "principal_id" in row:
            row["agent_id"] = str(row["principal_id"])
        return row

    def matches(self, conn, row, payload, readable):
        for field, value in payload.items():
            if value is None or field == "namespace":
                continue
            if field == "active_only":
                if value and row.get("ended_at") is not None:
                    return False
            elif field == "session_id":
                target = self.find(conn, readable, "sessions", value)
                if not target or str(row.get("session_id")) != str(target["id"]):
                    return False
            elif field in ("agent_id", "sender_agent", "receiver_agent", "user_id"):
                target = resolve(conn, value)
                expected = (str(target["id"]) if field == "agent_id" else target["slug"]
                            ) if target else value
                if (row.get(field) or "").lower() != expected.lower():
                    return False
            elif field in row and row[field] != value:
                return False
        return True
