"""Strict REST and v1-compatible memory operations share the same kernel."""

import re
from uuid import UUID

from cmh import audit
from cmh.kernel import DEFAULT_KINDS, TYPED
from cmh.policy.evaluator import deny, evaluate, namespace
from cmh.services.provenance import provenance, timestamp
from cmh.services.retrieval import PgVectorStore, graph, hybrid


class MemoryService:
    def __init__(self, entities):
        self.entities = entities
        self.identity = entities.identity
        self.vector_store = PgVectorStore()

    def store(self, context, payload, compatibility=False):
        path = payload.get("namespace", "org")
        if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", path):
            return self.identity.record(context, deny("NAMESPACE_FORBIDDEN", 5), "memory.write")
        # Permissions precede provenance. A denied scope never reaches a provider.
        with self.entities.engine.connect() as conn:
            result = evaluate(conn, context, "memory.write", path)
        if result["outcome"] != "ALLOW":
            return self.identity.record(context, result, "memory.write", path)
        content = payload.get("content")
        if (not isinstance(content, str) or not 1 <= len(content.strip()) <= 10000
            or (payload.get("title") is not None and not isinstance(payload["title"], str))):
            return self.identity.record(context, deny("VALIDATION_FAILED", 7), "memory.write", path)
        values, meta, invalid = provenance(context, payload, self.entities.now(), compatibility)
        if invalid:
            return self.identity.record(context, invalid, "memory.write", path)
        return self.entities.create(context, "memory", {"content": content.strip()}, values, path,
                                    title=payload.get("title"), legacy_meta=meta)

    def get(self, context, identity, as_of=None):
        result = None
        try:
            at = timestamp(as_of) if as_of else None
        except (TypeError, ValueError):
            return self.identity.record(context, deny("VALIDATION_FAILED", 7), "memory.read")
        with self.entities.engine.begin() as conn:
            result = evaluate(conn, context, "memory.read")
            if result["outcome"] == "ALLOW":
                readable = self.entities.scope(conn, context)
                row = self.entities.find(conn, readable, identity, ["memory"])
                body = self.entities.snapshot(conn, row, readable, at) if row else None
                if body:
                    body["pinecone_id"] = body.get("legacy_meta", {}).get("pinecone_id")
                    audit.append(conn, context, result, "memory.read", self.entities.now(),
                                 resource_id=row["id"], resource_type="memory")
                    return body
                result = deny("NOT_FOUND")
        return self.identity.record(context, result, "memory.read")

    def search(self, context, payload):
        query = payload.get("query")
        path = payload.get("namespace")
        op = "memory.read"
        if path is not None and (not isinstance(path, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", path,
        )):
            return self.identity.record(context, deny("NAMESPACE_FORBIDDEN", 5), op)
        with self.entities.engine.connect() as conn:
            result = evaluate(conn, context, op, path)
        if result["outcome"] != "ALLOW":
            return self.identity.record(context, result, op, path)
        try:
            if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
                raise ValueError
            limit = payload.get("limit", 10)
            depth = payload.get("depth", 3)
            if (isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50
                or isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 5):
                raise ValueError
            proposed = payload.get("kinds", DEFAULT_KINDS)
            if not isinstance(proposed, list) or any(kind not in TYPED for kind in proposed):
                raise ValueError
            at = timestamp(payload["as_of"]) if payload.get("as_of") else None
            anchor = UUID(payload["anchor_entity_id"]) if payload.get("anchor_entity_id") else None
        except (ValueError, TypeError, AttributeError):
            return self.identity.record(context, deny("VALIDATION_FAILED", 7), op, path)
        with self.entities.engine.begin() as conn:
            readable = self.entities.scope(conn, context)
            kinds = self.entities.kinds(context, proposed)
            ids = None
            if anchor:
                ids = graph(conn, readable, self.entities.kinds(context, list(TYPED)), anchor,
                            depth, at or self.entities.now(), historical=at is not None)
                if not ids:
                    result = deny("NOT_FOUND")
            if result["outcome"] == "ALLOW":
                node = namespace(conn, path) if path else None
                body = hybrid(conn, readable, kinds, query, self.entities.provider, self.vector_store,
                              namespace_id=node["id"] if node else None, candidate_ids=ids,
                              as_of=at, limit=limit)
                if body["degraded"]:
                    self.entities.read_only = True
                trace = {**result, "filters": {
                    "kinds": kinds, "namespace": path,
                    "anchor_entity_id": str(anchor) if anchor else None,
                    "depth": depth, "as_of": at.isoformat() if at else None,
                }, "result_count": len(body["results"]), "degraded": body["degraded"]}
                audit.append(conn, context, trace, op, self.entities.now(), path,
                             resource_type="search")
                return body
        return self.identity.record(context, result, op, path)
