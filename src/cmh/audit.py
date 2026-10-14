"""Append-only audit writer. Evaluate first; acquire a bounded lock only to append."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text

CHAIN_LOCK = 721043921


def encode(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value).lower()
    raise TypeError("Unexpected audit serialization type")


def canonical(event):
    return json.dumps(
        event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=encode,
    ).encode("utf-8")


def append(connection, context, decision, operation, now, namespace=None,
           resource_type="operation", resource_id=None):
    connection.execute(text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CHAIN_LOCK})
    previous = connection.execute(text(
        "SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1"
    )).scalar() or "0" * 64
    seq = connection.execute(text("SELECT nextval('audit_events_seq_seq')")).scalar_one()
    principal = context.principal if context else {}
    credential = context.credential if context else None
    metadata = context.request_meta if context else {}
    namespace_id = None
    if namespace:
        namespace_id = connection.execute(text(
            "SELECT id FROM namespaces WHERE path=CAST(:path AS ltree)"
        ), {"path": namespace}).scalar()
    event = {
        "seq": seq, "id": uuid4(), "occurred_at": now,
        "principal_id": principal.get("id"), "sponsor_id": principal.get("sponsor_id"),
        "actor": context.actor if context else "unauthenticated",
        "credential_id": credential["id"] if credential else None,
        "surface": metadata.get("surface", "system"),
        "operation": operation, "resource_type": resource_type,
        "resource_id": resource_id, "namespace_id": namespace_id, "namespace": namespace,
        "outcome": decision["outcome"], "record_status": None,
        "decision_trace": decision, "request_meta": metadata,
    }
    digest = hashlib.sha256(previous.encode("ascii") + canonical(event)).hexdigest()
    values = {**event, "prev_hash": previous, "hash": digest,
              "decision_trace": json.dumps(decision, default=encode),
              "request_meta": json.dumps(metadata, default=encode)}
    columns = list(values)
    parameters = [
        f"CAST(:{key} AS jsonb)" if key in ("decision_trace", "request_meta") else f":{key}"
        for key in columns
    ]
    connection.execute(text(
        "INSERT INTO audit_events (" + ",".join(columns) + ") VALUES ("
        + ",".join(parameters) + ")"
    ), values)
    return seq


def verify(connection):
    previous = "0" * 64
    for row in connection.execute(text("SELECT * FROM audit_events ORDER BY seq")).mappings():
        event = {key: value for key, value in row.items() if key not in ("hash", "prev_hash")}
        digest = hashlib.sha256(previous.encode("ascii") + canonical(event)).hexdigest()
        if row["prev_hash"] != previous or row["hash"] != digest:
            return {"valid": False, "bad_seq": row["seq"]}
        previous = row["hash"]
    return {"valid": True, "head_hash": previous}
