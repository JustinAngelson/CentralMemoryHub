"""Atomic entity/version/typed/vector/audit writes and explicitly scoped reads."""

import json
from datetime import timedelta
from threading import RLock
from uuid import UUID, uuid4

from sqlalchemy import text

from cmh import audit
from cmh.kernel import MIRRORED, TYPED, operation
from cmh.policy.evaluator import deny, evaluate, namespace
from cmh.policy.readable import readable_namespaces
from cmh.policy.scopes import envelope, has_scope
from cmh.services.embedding import EmbeddingUnavailable
from cmh.services.provenance import provenance as validate_provenance


def encode(value):
    return json.dumps(value, default=str)


def public_snapshot(snapshot):
    return {key: value for key, value in snapshot.items()
            if not key.startswith("__") and key != "search_tsv"}


class EntityService:
    def __init__(self, identity, provider, retry_seconds=60):
        self.identity = identity
        self.engine = identity.engine
        self.now = identity.now
        self.provider = provider
        self.read_only = False
        self.retry_seconds = retry_seconds
        self.retry_at = None
        self.provider_lock = RLock()
        self.after_version = None

    def embedding_failed(self, at=None):
        with self.provider_lock:
            self.read_only = True
            self.retry_at = (at or self.now()) + timedelta(seconds=self.retry_seconds)

    def embedding_ready(self):
        # One probe per process after the cooldown; denied/invalid callers never reach this.
        with self.provider_lock:
            if not self.read_only:
                return True
            if self.retry_at is not None and self.now() < self.retry_at:
                return False
            try:
                self.provider.embed("cmh embedding readiness")
            except EmbeddingUnavailable:
                self.embedding_failed()
                return False
            self.read_only = False
            self.retry_at = None
            return True

    def scope(self, connection, context):
        if "readable" not in context.policy_cache:
            context.policy_cache["readable"] = readable_namespaces(
                connection, context.principal,
            )
        readable = context.policy_cache["readable"]
        connection.execute(text("SELECT set_config('cmh.readable_namespaces',:value,true)"),
                           {"value": ",".join(readable)})
        return readable

    def kinds(self, context, proposed):
        credential = context.credential
        principal_scopes = credential["scopes"] if (
            context.principal["kind"] == "service" and credential
        ) else envelope(context.principal)
        return [kind for kind in proposed if kind in TYPED and
                has_scope(principal_scopes, operation(kind)) and
                (not credential or has_scope(credential["scopes"], operation(kind)))]

    def find(self, connection, readable, identity, kinds=None):
        # UUID and legacy identities are both resolved within the same explicit namespace filter.
        table, old_id = "unstructured_data", identity
        entity_id = None
        if identity.startswith("v1:"):
            parts = identity.split(":", 2)
            if len(parts) != 3:
                return None
            table, old_id = parts[1:]
        else:
            try:
                entity_id = UUID(identity)
            except ValueError:
                pass
        row = connection.execute(text("""
          SELECT * FROM entities WHERE namespace_id=ANY(CAST(:readable AS uuid[]))
            AND kind=ANY(CAST(:kinds AS text[]))
            AND (id=:id OR (legacy_meta->>'v1_table'=:table AND legacy_meta->>'v1_id'=:old_id))
          ORDER BY (id=:id) DESC NULLS LAST LIMIT 1
        """), {"readable": readable, "kinds": kinds if kinds is not None else list(TYPED),
               "id": entity_id,
               "table": table, "old_id": old_id}).mappings().first()
        return dict(row) if row else None

    def snapshot(self, connection, row, readable, as_of=None):
        if as_of:
            value = connection.execute(text("""
              SELECT snapshot FROM entity_versions v JOIN entities e ON e.id=v.entity_id
              WHERE entity_id=:id AND changed_at<=:at
                AND e.namespace_id=ANY(CAST(:readable AS uuid[]))
              ORDER BY version DESC LIMIT 1
            """), {"id": row["id"], "at": as_of, "readable": readable}).scalar()
            return public_snapshot(value) if value else None
        table, _ = TYPED[row["kind"]]
        data = connection.execute(text(f"""
          SELECT t.* FROM {table} t JOIN entities e ON e.id=t.id
          WHERE t.id=:id AND e.namespace_id=ANY(CAST(:readable AS uuid[]))
        """), {"id": row["id"], "readable": readable}).mappings().one()
        return public_snapshot({**row, **data, "__search_tsv": row.get("search_tsv")}) | {
            "pinecone_id": row["legacy_meta"].get("pinecone_id"),
        }

    def version(self, connection, context, snapshot, change_kind, vector):
        # search_text is a derived retrieval index, not another copy of the
        # typed content in the immutable version. The embedding is retained.
        snapshot = {key: value for key, value in snapshot.items()
                    if key not in ("search_tsv", "search_text")}
        # Keep the native v2 vector with its immutable snapshot for historical semantic
        # retrieval. Historical v1 context_embedding remains legacy_meta only (P7).
        snapshot["__embedding"] = vector
        snapshot["__embedding_model"] = self.provider.model
        connection.execute(text("""
          INSERT INTO entity_versions(entity_id,version,snapshot,status,change_kind,
            changed_by,actor,changed_at)
          VALUES(:id,:version,CAST(:snapshot AS jsonb),:status,:change,:principal,:actor,:now)
        """), {"id": snapshot["id"], "version": snapshot["current_version"],
               "snapshot": encode(snapshot), "status": snapshot["status"], "change": change_kind,
               "principal": context.id, "actor": context.actor, "now": self.now()})
        if self.after_version:
            self.after_version(connection, snapshot["id"])
        connection.execute(text("""
          INSERT INTO embeddings(entity_id,model,entity_version,embedding,created_at)
          VALUES(:id,:model,:version,CAST(:vector AS vector),:now)
          ON CONFLICT(entity_id,model) DO UPDATE SET
            entity_version=excluded.entity_version,embedding=excluded.embedding,
            created_at=excluded.created_at
        """), {"id": snapshot["id"], "model": self.provider.model,
               "version": snapshot["current_version"], "vector": encode(vector), "now": self.now()})

    def create(self, context, kind, data, provenance, path="org", title=None, legacy_meta=None,
               about=None, _import_record=None):
        if _import_record is not None:
            _import_record.validate(context)
        op = operation(kind, True)
        result = None
        try:
            with self.engine.begin() as conn:
                result = evaluate(conn, context, op, path)
                if result["outcome"] == "ALLOW" and _import_record:
                    result = {**result, "import": _import_record.trace}
                if (legacy_meta or {}).get("claimed_identity_mismatch"):
                    result = {**result, "claimed_identity_mismatch": True}
                if result["outcome"] == "ALLOW" and kind not in TYPED:
                    result = deny("VALIDATION_FAILED", 7)
                if result["outcome"] == "ALLOW" and kind in MIRRORED:
                    result = deny("MIRRORED_KIND_FORBIDDEN", 6)
                if result["outcome"] == "ALLOW" and not self.embedding_ready():
                    result = deny("READ_ONLY_MODE")
                if result["outcome"] == "ALLOW":
                    values, _meta, invalid = validate_provenance(context, provenance, self.now())
                    if invalid:
                        result = invalid
                    else:
                        provenance = values
                if result["outcome"] == "ALLOW":
                    readable = self.scope(conn, context)
                    node = namespace(conn, path)
                    target = self.find(conn, readable, str(about), self.kinds(
                        context, ["memory"],
                    )) if about else None
                    if kind == "memory_link" and not target:
                        result = deny("EDGE_ENDPOINT_FORBIDDEN", 5)
                if result["outcome"] == "ALLOW":
                    identity = uuid4()
                    table, columns = TYPED[kind]
                    if set(data) - columns.keys():
                        result = deny("VALIDATION_FAILED", 7)
                    else:
                        search_text = " ".join(str(value) for value in data.values()
                                               if value is not None)
                        if kind == "memory_link" and not title and not search_text:
                            title = "Memory link"
                        vector = self.provider.embed((title or "") + "\n" + search_text)
                        row = dict(conn.execute(text("""
                          INSERT INTO entities(id,kind,namespace_id,title,search_text,
                            author_principal_id,actor,source_type,source_ref,confidence,
                            occurred_at,legacy_meta,created_at,updated_at)
                          VALUES(:id,:kind,:namespace,:title,:content,:author,:actor,:source_type,
                            :source_ref,:confidence,:occurred_at,CAST(:meta AS jsonb),:created,:updated)
                          RETURNING *
                        """), {"id": identity, "kind": kind, "namespace": node["id"],
                               "title": title, "content": search_text,
                               "author": _import_record.author if _import_record else context.id,
                               "actor": context.actor, **provenance, "meta": encode(legacy_meta or {}),
                               "created": _import_record.created_at if _import_record else self.now(),
                               "updated": _import_record.updated_at if _import_record else self.now()
                               }).mappings().one())
                        fields = ["id", *data]
                        values = {"id": identity, **data}
                        expressions = [":" + name for name in fields]
                        for name, value in data.items():
                            if columns[name] == "jsonb":
                                expressions[fields.index(name)] = f"CAST(:{name} AS jsonb)"
                                values[name] = encode(value)
                        conn.execute(text(f"INSERT INTO {table} ({','.join(fields)}) "
                                          f"VALUES ({','.join(expressions)})"), values)
                        if kind == "memory_link":
                            conn.execute(text("""
                              INSERT INTO edges(src_entity_id,dst_entity_id,type,
                                author_principal_id,actor,status)
                              VALUES(:src,:dst,'about',:author,:actor,'active')
                            """), {"src": identity, "dst": target["id"],
                                   "author": context.id, "actor": context.actor})
                        typed = dict(conn.execute(text(f"""
                          SELECT t.* FROM {table} t JOIN entities e ON e.id=t.id WHERE t.id=:id
                            AND e.namespace_id=ANY(CAST(:readable AS uuid[]))
                        """), {"id": identity, "readable": readable}).mappings().one())
                        snapshot = {**row, **typed}
                        self.version(conn, context, snapshot, "create", vector)
                        audit.append(conn, context, result, op, self.now(), path,
                                     resource_type=kind, resource_id=identity)
                        return public_snapshot(snapshot) | {
                            "pinecone_id": (legacy_meta or {}).get("pinecone_id"),
                        }
        except EmbeddingUnavailable:
            self.embedding_failed()
            result = deny("READ_ONLY_MODE")
        # The state transaction ended before an independent DENY audit append.
        if (legacy_meta or {}).get("claimed_identity_mismatch"):
            result = {**result, "claimed_identity_mismatch": True}
        if _import_record:
            result = {**result, "import": _import_record.trace}
        return self.identity.record(context, result, op, path)

    def update(self, context, identity, data, expected_kind=None, legacy_meta=None):
        result = deny("NOT_FOUND")
        path = None
        op = operation(expected_kind, True) if expected_kind else "entities.update"
        try:
            with self.engine.begin() as conn:
                readable = self.scope(conn, context)
                row = self.find(conn, readable, str(identity), self.kinds(
                    context, [expected_kind] if expected_kind else list(TYPED),
                ))
                if row:
                    path = conn.execute(text("SELECT path::text FROM namespaces WHERE id=:id"),
                                        {"id": row["namespace_id"]}).scalar_one()
                    result = evaluate(conn, context, operation(row["kind"], True), path)
                    if (legacy_meta or {}).get("claimed_identity_mismatch"):
                        result = {**result, "claimed_identity_mismatch": True}
                    if result["outcome"] == "ALLOW" and row["kind"] in MIRRORED:
                        result = deny("MIRRORED_KIND_FORBIDDEN", 6)
                    if result["outcome"] == "ALLOW" and not self.embedding_ready():
                        result = deny("READ_ONLY_MODE")
                if row and result["outcome"] == "ALLOW":
                    # Lock before loading current state; concurrent updates never reuse a version.
                    row = dict(conn.execute(text("""
                      SELECT * FROM entities WHERE id=:id
                        AND namespace_id=ANY(CAST(:readable AS uuid[])) FOR UPDATE
                    """), {"id": row["id"], "readable": readable}).mappings().one())
                    table, columns = TYPED[row["kind"]]
                    if set(data) - columns.keys():
                        result = deny("VALIDATION_FAILED", 7)
                    else:
                        current = dict(conn.execute(text(f"""
                          SELECT t.* FROM {table} t JOIN entities e ON e.id=t.id WHERE t.id=:id
                            AND e.namespace_id=ANY(CAST(:readable AS uuid[]))
                        """), {"id": row["id"], "readable": readable}).mappings().one())
                        current.update(data)
                        content = " ".join(str(value) for key, value in current.items()
                                           if key != "id" and value is not None)
                        vector = self.provider.embed((row["title"] or "") + "\n" + content)
                        for field, value in data.items():
                            cast = "CAST(:value AS jsonb)" if columns[field] == "jsonb" else ":value"
                            conn.execute(text(f"UPDATE {table} SET {field}={cast} WHERE id=:id"),
                                         {"id": row["id"], "value": encode(value)
                                          if columns[field] == "jsonb" else value})
                        row = dict(conn.execute(text("""
                          UPDATE entities SET current_version=current_version+1,
                            search_text=:content,updated_at=:now,legacy_meta=CAST(:meta AS jsonb)
                          WHERE id=:id AND namespace_id=ANY(CAST(:readable AS uuid[])) RETURNING *
                        """), {"id": row["id"], "content": content,
                               "readable": readable, "meta": encode(legacy_meta or row["legacy_meta"]),
                               "now": self.now()}).mappings().one())
                        snapshot = {**row, **current}
                        self.version(conn, context, snapshot, "update", vector)
                        audit.append(conn, context, result, operation(row["kind"], True),
                                     self.now(), path, resource_id=row["id"])
                        return public_snapshot(snapshot)
        except EmbeddingUnavailable:
            self.embedding_failed()
            result = deny("READ_ONLY_MODE")
        if (legacy_meta or {}).get("claimed_identity_mismatch"):
            result = {**result, "claimed_identity_mismatch": True}
        return self.identity.record(context, result, op, path)
