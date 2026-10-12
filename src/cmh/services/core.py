"""Transaction coordinator: evaluate first, then exactly one bounded audit append."""

from cmh import audit
from cmh.policy.evaluator import allow, evaluate


class IdentityService:
    def __init__(self, engine, now):
        self.engine = engine
        self.now = now

    def record(self, context, decision, operation, namespace=None):
        # This is only called after the evaluation/read transaction has ended.
        with self.engine.begin() as connection:
            audit.append(connection, context, decision, operation, self.now(), namespace)
        return decision

    def perform(self, context, operation, namespace=None, change=None, preflight=None,
                decision=None):
        with self.engine.begin() as connection:
            result = decision or evaluate(connection, context, operation, namespace)
            if result["outcome"] == "ALLOW" and preflight:
                result = preflight(connection) or result
            if result["outcome"] == "ALLOW":
                value = change(connection) if change else result
                audit.append(connection, context, result, operation, self.now(), namespace)
                return value
        # No chain lock or uncommitted state is retained across this boundary.
        return self.record(context, result, operation, namespace)

    def check(self, context, operation, namespace):
        import re

        from cmh.policy.evaluator import deny

        if namespace and not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", namespace):
            return self.record(context, deny("NAMESPACE_FORBIDDEN", 5), operation)
        return self.perform(context, operation, namespace)

    def whoami(self, context):
        def data(connection):
            from sqlalchemy import text

            from cmh.policy.evaluator import can_access, principal
            from cmh.policy.scopes import envelope

            subject = context.principal
            sponsor = principal(connection, subject["sponsor_id"]) if subject["sponsor_id"] else None
            grants = []
            for path in connection.execute(text("SELECT path::text FROM namespaces")).scalars():
                if can_access(connection, subject, path):
                    grants.append({"namespace": path, "access": "write" if can_access(
                        connection, subject, path, True,
                    ) else "read"})
            credential = context.credential
            return {
                "principal": subject["slug"], "kind": subject["kind"], "role": subject["role"],
                "tier": subject["tier"], "sponsor": sponsor["slug"] if sponsor else None,
                "actor": context.actor, "credential_kind": credential["kind"] if credential else None,
                "ai_client": bool(credential and credential["ai_client"]),
                "scopes": credential["scopes"] if credential else sorted(envelope(subject)),
                "grants": grants,
            }
        # Authentication is sufficient to inspect one's own claims, including
        # a minimal sync token without directory.read. This reveals no records.
        return self.perform(context, "identity.whoami", change=data, decision=allow())

    def protocol(self, context, operation="mcp.transport"):
        return self.perform(context, operation, decision=allow())
