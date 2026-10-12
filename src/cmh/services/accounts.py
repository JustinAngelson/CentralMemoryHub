"""Human password/session lifecycle. No credential material enters audit payloads."""

import hashlib
import hmac
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import text

from cmh.auth.context import PrincipalContext
from cmh.policy.evaluator import allow, deny, principal


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def password_hasher():
    # No weaker fallback. This dependency is declared by the v2 manifest.
    from argon2 import PasswordHasher

    return PasswordHasher()


def session(connection, user_id, now, meta):
    value = secrets.token_urlsafe(32)
    connection.execute(text("""
      INSERT INTO admin_sessions(id_hash,user_id,created_at,last_seen_at,expires_at,ip,user_agent)
      VALUES(:hash,:user,:now,:now,:expires,:ip,:agent)
    """), {"hash": digest(value), "user": user_id, "now": now,
           "expires": now + timedelta(hours=12), "ip": meta.get("client_ip"),
           "agent": None})
    return value


def bootstrap(service, payload, supplied, expected, meta):
    from cmh import audit

    empty = PrincipalContext({}, request_meta=meta)
    if not supplied or not hmac.compare_digest(supplied, expected):
        return service.record(empty, deny("AUTH_INVALID" if supplied else "AUTH_MISSING"),
                              "bootstrap"), None
    with service.engine.connect() as connection:
        consumed = connection.execute(text("SELECT 1 FROM bootstrap_state")).scalar()
    if consumed:
        return service.record(empty, deny("AUTH_REVOKED"), "bootstrap"), None
    if (
        len(payload.get("password", "")) < 14 or not payload.get("email")
        or not payload.get("display_name")
    ):
        return service.record(empty, deny("VALIDATION_FAILED"), "bootstrap"), None
    hashed = password_hasher().hash(payload["password"])
    now = service.now()
    identity = uuid4()
    user = uuid4()
    with service.engine.begin() as connection:
        # Serialize competing bootstrap requests before testing consumption.
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SELECT pg_advisory_xact_lock(721043920)"))
        if connection.execute(text("SELECT 1 FROM bootstrap_state")).scalar():
            result = None
        else:
            subject = connection.execute(text("""
              INSERT INTO principals(id,kind,slug,display_name,role,tier,created_by)
              VALUES(:id,'human',:slug,:display,'owner',4,:id) RETURNING *
            """), {"id": identity, "slug": payload["slug"],
                   "display": payload["display_name"]}).mappings().one()
            connection.execute(text("""
              INSERT INTO users(id,principal_id,email,password_hash)
              VALUES(:user,:principal,:email,:password)
            """), {"user": user, "principal": identity, "email": payload["email"].lower(),
                   "password": hashed})
            connection.execute(text("""
              INSERT INTO namespaces(path,owner_principal_id,created_by)
              VALUES(CAST(:path AS ltree),:id,:id)
            """), {"path": "people." + payload["slug"] + ".private", "id": identity})
            connection.execute(text("""
              INSERT INTO bootstrap_state(consumed_at,owner_principal_id) VALUES(:now,:id)
            """), {"now": now, "id": identity})
            value = session(connection, user, now, meta)
            context = PrincipalContext(dict(subject), request_meta=meta)
            audit.append(connection, context, allow(), "bootstrap", now)
            result = {"principal": dict(subject)}, value
    if result is None:
        return service.record(empty, deny("AUTH_REVOKED"), "bootstrap"), None
    return result


def login(service, payload, meta):
    from argon2.exceptions import VerificationError

    from cmh import audit

    empty = PrincipalContext({}, request_meta=meta)
    now = service.now()
    status = None
    with service.engine.begin() as connection:
        user = connection.execute(text(
            "SELECT * FROM users WHERE lower(email)=lower(:email) FOR UPDATE"
        ), {"email": payload.get("email", "")}).mappings().first()
        if not user:
            status = "AUTH_INVALID"
        elif user["locked_until"] and user["locked_until"] > now:
            status = "AUTH_LOCKED"
        else:
            try:
                password_hasher().verify(user["password_hash"], payload.get("password", ""))
                correct = True
            except VerificationError:
                correct = False
            if not correct:
                failures = user["failed_logins"] + 1
                connection.execute(text("""
                  UPDATE users SET failed_logins=:n,locked_until=:until WHERE id=:id
                """), {"n": failures, "until": now + timedelta(minutes=15)
                       if failures >= 10 else None, "id": user["id"]})
                status = "AUTH_INVALID"
            else:
                subject = principal(connection, user["principal_id"])
                if subject["status"] != "active":
                    status = "PRINCIPAL_INACTIVE"
                else:
                    connection.execute(text("""
                      UPDATE users SET failed_logins=0,locked_until=NULL,last_login_at=:now
                      WHERE id=:id
                    """), {"now": now, "id": user["id"]})
                    value = session(connection, user["id"], now, meta)
                    context = PrincipalContext(subject, request_meta=meta)
                    audit.append(connection, context, allow(), "admin.login", now)
                    return {"principal": subject}, value
    # Counters are AUTHN state, committed before a denial append. No chain lock
    # was acquired in the counter transaction.
    return service.record(empty, deny(status), "admin.login"), None


def logout(service, context):
    def change(connection):
        connection.execute(text(
            "UPDATE admin_sessions SET revoked_at=:now WHERE id_hash=:hash"
        ), {"now": service.now(), "hash": context.session_hash})
        return {"outcome": "ALLOW"}
    # A session logout is available to every active human, not just stewards.
    return service.perform(context, "admin.logout", change=change, decision=allow())
