"""One compatibility dispatch to existing permission, identity and audit services."""

from sqlalchemy import text

from cmh.kernel import operation
from cmh.policy.evaluator import allow, deny
from cmh.services.compat_common import KINDS
from cmh.services.compat_entities import CompatEntities
from cmh.services.compat_operations import CompatOperations


class CompatService:
    def __init__(self, memory):
        self.memory = memory
        self.entities = memory.entities
        self.identity = self.entities.identity
        self.operational = CompatOperations(self.entities)
        self.native = CompatEntities(self.entities, self.operational)

    def scope(self, name):
        if name == "cmh_store_memory":
            return "memory.write"
        if name in ("cmh_get_memory", "cmh_search_memory"):
            return "memory.read"
        action = name.removeprefix("cmh_")
        if action in KINDS:
            return operation(KINDS[action], action.startswith((
                "create_", "update_", "store_", "log_",
            )) or action == "share_context")
        return ("directory.read" if name == "cmh_list_agents" else "health.read"
                if name == "cmh_health_check" else "principals.admin"
                if name == "cmh_register_agent" else "messages.write"
                if name in ("cmh_create_session", "cmh_end_session", "cmh_send_message")
                else "messages.read")

    def register_denial(self, context):
        # Always disabled, including legacy Phase 1 top-level argument shapes.
        decision = deny("TIER_FORBIDDEN", 3) if context.principal["role"] == "external" else (
            deny("PRINCIPAL_CREATION_FORBIDDEN", 6) if context.principal["kind"] != "human"
            else deny("AI_CLIENT_CEILING", 2)
        )
        return self.identity.record(context, decision, "principals.admin")

    def call(self, context, name, payload):
        if name == "cmh_register_agent":
            return self.register_denial(context)
        if name == "cmh_health_check":
            with self.entities.engine.begin() as conn:
                readable = self.entities.scope(conn, context)
                agents = conn.execute(text("""
                  SELECT count(*) FROM agent_directory d JOIN principals p ON p.id=d.principal_id
                  WHERE p.kind='agent'
                """)).scalar_one()
                memories = conn.execute(text("""
                  SELECT count(*) FROM entities WHERE kind='memory'
                    AND namespace_id=ANY(CAST(:readable AS uuid[]))
                """), {"readable": readable}).scalar_one()
            self.identity.record(context, allow(), "health.read")
            return {"database": "ok", "pinecone": "not_used", "agent_count": agents,
                    "memory_count": memories}
        if name in ("cmh_list_agents", "cmh_create_session", "cmh_end_session",
                    "cmh_list_sessions", "cmh_send_message", "cmh_list_messages"):
            return self.operational.call(context, name, payload)
        return self.native.call(context, name, payload)
