"""Separate bearer/session surfaces; session_user privilege guard lives in db."""

from datetime import timedelta

from sqlalchemy import text

from cmh.auth.context import PrincipalContext
from cmh.policy.evaluator import deny, principal
from cmh.services.accounts import digest


def active(context, connection):
    subject = context.principal
    if subject["status"] != "active":
        return deny("PRINCIPAL_SUSPENDED" if subject["status"] == "suspended"
                    else "PRINCIPAL_INACTIVE")
    if subject["sponsor_id"]:
        sponsor = principal(connection, subject["sponsor_id"])
        if not sponsor or sponsor["status"] != "active":
            return deny("PRINCIPAL_SUSPENDED")
    return None


def bearer(engine, authorization, now, limits, meta, bootstrap_token):
    empty = PrincipalContext({}, request_meta=meta)
    if not authorization:
        return empty, deny("AUTH_MISSING"), 401
    pieces = authorization.split(" ")
    if len(pieces) != 2 or pieces[0].lower() != "bearer" or not pieces[1]:
        return empty, deny("AUTH_INVALID"), 401
    value = pieces[1]
    if value == bootstrap_token or value.startswith("cmh_at_"):
        return empty, deny("AUTH_INVALID"), 401
    kind = "api" if value.startswith("cmh_ak_") else (
        "personal_ai_client" if value.startswith("cmh_pk_") else "legacy_shared"
    )
    if value.startswith("cmh_") and kind == "legacy_shared":
        return empty, deny("AUTH_INVALID"), 401
    with engine.begin() as connection:
        credential = connection.execute(text(
            "SELECT * FROM credentials WHERE token_hash=:hash AND kind=:kind"
        ), {"hash": digest(value), "kind": kind}).mappings().first()
        if not credential:
            return empty, deny("AUTH_INVALID"), 401
        public = {key: item for key, item in credential.items() if key != "token_hash"}
        subject = principal(connection, credential["principal_id"])
        context = PrincipalContext(subject, public, request_meta=meta)
        if credential["revoked_at"]:
            return context, deny("AUTH_REVOKED"), 401
        if credential["expires_at"] and credential["expires_at"] <= now:
            return context, deny("AUTH_EXPIRED"), 401
        rejection = active(context, connection)
        if rejection:
            return context, rejection, 403
        retry = limits.credential(credential["id"], credential["rate_limit"], now)
        if retry:
            return context, deny("RATE_LIMITED"), 429
        if not credential["last_used_at"] or now - credential["last_used_at"] >= timedelta(minutes=1):
            connection.execute(text("""
              UPDATE credentials SET last_used_at=:now WHERE id=:id
                AND (last_used_at IS NULL OR last_used_at <= :threshold)
            """), {"now": now, "id": credential["id"], "threshold": now - timedelta(minutes=1)})
    return context, None, 200


def cookie(engine, value, now, meta):
    empty = PrincipalContext({}, request_meta=meta)
    if not value:
        return empty, deny("AUTH_MISSING"), 401
    hashed = digest(value)
    with engine.begin() as connection:
        record = connection.execute(text("""
          SELECT s.*,u.principal_id FROM admin_sessions s JOIN users u ON u.id=s.user_id
          WHERE s.id_hash=:hash
        """), {"hash": hashed}).mappings().first()
        if not record:
            return empty, deny("AUTH_INVALID"), 401
        subject = principal(connection, record["principal_id"])
        context = PrincipalContext(subject, session_hash=hashed, request_meta=meta)
        if record["revoked_at"]:
            return context, deny("AUTH_REVOKED"), 401
        if record["expires_at"] <= now or now - record["created_at"] >= timedelta(days=7):
            return context, deny("AUTH_EXPIRED"), 401
        rejection = active(context, connection)
        if rejection:
            return context, rejection, 403
        connection.execute(text("""
          UPDATE admin_sessions SET last_seen_at=:now,expires_at=:expires WHERE id_hash=:hash
        """), {"hash": hashed, "now": now,
               "expires": min(now + timedelta(hours=12), record["created_at"] + timedelta(days=7))})
    return context, None, 200
