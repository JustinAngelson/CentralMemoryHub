"""JSON admin identity operations. All permissions and mutations use one service."""

import json
import re
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import text

from cmh import audit
from cmh.policy.evaluator import allow, can_access, deny, evaluate, namespace, principal
from cmh.policy.scopes import ceiling, envelope, expand
from cmh.services.accounts import digest, password_hasher


def template(connection, name):
    row = connection.execute(text(
        "SELECT * FROM credential_templates WHERE name=:name AND active=true"
    ), {"name": name}).mappings().first()
    return dict(row) if row else None


def owner(connection):
    return connection.execute(text(
        "SELECT * FROM principals WHERE role='owner'"
    )).mappings().one()


def private_namespace(connection, subject, created_by):
    path = ("people." if subject["kind"] == "human" else "agents.") + subject["slug"] + ".private"
    connection.execute(text("""
      INSERT INTO namespaces(path,owner_principal_id,created_by)
      VALUES(CAST(:path AS ltree),:principal,:creator)
    """), {"path": path, "principal": subject["id"], "creator": created_by})
    return path


def notify(connection, issuer, target, credential, selected, now):
    # Only identifiers belong in outbox payloads. Never tokens, hashes or passwords.
    connection.execute(text("""
      INSERT INTO notifications(recipient_principal_id,kind,payload,created_at)
      VALUES(:owner,'credential_issued',CAST(:payload AS jsonb),:now)
    """), {"owner": owner(connection)["id"], "now": now,
           "payload": json.dumps({"principal_id": str(target["id"]),
                                  "credential_id": str(credential["id"]),
                                  "template_id": str(selected["id"]),
                                  "issued_by": str(issuer["id"])})})


def mint(connection, issuer, target, selected, payload, now):
    personal = selected["name"].startswith("personal-ai-client")
    scopes = expand(payload.get("scopes", selected["scopes"])) if target["kind"] == "service" else (
        sorted(envelope(target)) if personal else expand(selected["scopes"])
    )
    if personal:
        scopes = [scope for scope in scopes if not ceiling(scope)]
        if selected["name"].endswith("-readonly"):
            from cmh.policy.scopes import OBSERVER

            scopes = [scope for scope in scopes if scope in OBSERVER]
    value = ("cmh_pk_" if personal else "cmh_ak_") + secrets.token_urlsafe(32)
    credential = connection.execute(text("""
      INSERT INTO credentials(principal_id,token_hash,token_prefix,name,kind,client_label,
        ai_client,scopes,template_id,issued_by,created_at,expires_at)
      VALUES(:principal,:hash,:prefix,:name,:kind,:label,:ai,:scopes,:template,:issuer,:now,:expires)
      RETURNING id,principal_id,token_prefix,name,kind,ai_client,scopes,template_id,expires_at
    """), {"principal": target["id"], "hash": digest(value),
           "prefix": value[:11], "name": payload.get("name", payload.get("credential_name", "runtime")),
           "kind": "personal_ai_client" if personal else "api",
           "label": payload.get("client_label"), "ai": personal, "scopes": scopes,
           "template": selected["id"], "issuer": issuer["id"], "now": now,
           "expires": now + timedelta(days=selected["default_expiry_days"])}).mappings().one()
    notify(connection, issuer, target, credential, selected, now)
    return {**credential, "token": value}


def queue(service, context, operation, payload, selected):
    # Principal/credential creation has not occurred. The queue record and its
    # audit commit independently, with no outer chain lock or state transaction.
    decision = {**allow(), "outcome": "QUEUE", "code": "OWNER_APPROVAL_REQUIRED",
                "template_id": str(selected["id"])}
    safe_keys = {
        "kind", "slug", "display_name", "role", "tier", "sponsor_id", "template",
        "credential_name", "principal_id", "name", "namespace_grants", "namespaces", "scopes",
    }
    safe = {key: value for key, value in payload.items() if key in safe_keys}
    with service.engine.begin() as connection:
        identity = uuid4()
        connection.execute(text("""
          INSERT INTO approvals(id,requester_id,required_reviewer_id,operation,payload,
            created_at,expires_at) VALUES(:id,:requester,:owner,:operation,CAST(:payload AS jsonb),
            :now,:expires)
        """), {"id": identity, "requester": context.id, "owner": owner(connection)["id"],
               "operation": operation, "payload": json.dumps(safe), "now": service.now(),
               "expires": service.now() + timedelta(days=14)})
        audit.append(connection, context, decision, operation, service.now())
    return {**decision, "approval_id": identity}


def create_principal(service, context, payload, approved=False, approval_id=None, reviewer=None):
    human = payload.get("kind") == "human"
    operation = "principals.admin" if human else "credentials.issue_sponsored"
    with service.engine.connect() as connection:
        selected = None if human else template(connection, payload.get("template"))
        preliminary = evaluate(connection, context, operation)
        if preliminary["outcome"] == "ALLOW":
            if payload.get("kind") not in {"human", "agent", "service"}:
                preliminary = deny("VALIDATION_FAILED")
            elif "bundle:sync" in payload.get("scopes", []) and payload["scopes"] != ["bundle:sync"]:
                preliminary = deny("SCOPE_MISSING", 2)
            elif not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", payload.get("slug", "")):
                preliminary = deny("VALIDATION_FAILED")
            elif not human and not selected:
                preliminary = deny("TEMPLATE_NOT_FOUND")
            elif not human and payload.get("tier") is not None and payload["tier"] > 3:
                preliminary = deny("TIER_FORBIDDEN", 3)
            elif human and (payload.get("role") != "partner" or len(payload.get("password", "")) < 14):
                preliminary = deny("VALIDATION_FAILED")
            elif not human and not payload.get("sponsor_id"):
                preliminary = deny("SPONSOR_REQUIRED", 4)
            elif not human:
                sponsor = principal(connection, payload["sponsor_id"])
                if (
                    not sponsor or sponsor["kind"] != "human" or sponsor["status"] != "active"
                    or (selected["target_role"] == "external" and sponsor["role"] != "owner")
                    or (context.principal["role"] != "owner" and sponsor["id"] != context.id
                        and selected["target_role"] != "external")
                    or (payload.get("kind") == "agent" and
                        selected["target_tier"] > sponsor["tier"])
                ):
                    preliminary = deny("SPONSOR_CEILING", 4)
                elif payload.get("kind") == "service" and context.principal["role"] != "owner":
                    preliminary = deny("TIER_FORBIDDEN", 3)
                else:
                    for proposed in selected["namespace_grants_template"]:
                        path = proposed["path"]
                        if "<slug>" not in path and not can_access(
                            connection, sponsor, path, proposed["access"] == "write",
                        ):
                            preliminary = deny("SPONSOR_CEILING", 4)
                            break
    if preliminary["outcome"] != "ALLOW":
        return service.record(context, preliminary, operation)
    sync = payload.get("kind") == "service" and payload.get("scopes") == ["bundle:sync"]
    if selected and selected["requires_owner_approval"] and not approved and not sync:
        return queue(service, context, operation, payload, selected)
    hashed = password_hasher().hash(payload["password"]) if human else None

    def change(connection):
        if approval_id:
            approval = connection.execute(text(
                "SELECT status FROM approvals WHERE id=:id FOR UPDATE"
            ), {"id": approval_id}).scalar_one()
            if approval != "pending":
                raise ValueError("Approval is no longer pending")
        identity = uuid4()
        kind = payload.get("kind", "agent")
        subject = dict(connection.execute(text("""
          INSERT INTO principals(id,kind,slug,display_name,role,tier,sponsor_id,created_by)
          VALUES(:id,:kind,:slug,:display,:role,:tier,:sponsor,:creator) RETURNING *
        """), {"id": identity, "kind": kind, "slug": payload["slug"],
               "display": payload.get("display_name", payload["slug"]),
               "role": payload["role"] if human else (
                   selected["target_role"] if kind == "agent" else None
               ),
               "tier": payload.get("tier", 3) if human else (
                   selected["target_tier"] if kind == "agent" else None
               ),
               "sponsor": None if human else payload["sponsor_id"],
               "creator": context.id}).mappings().one())
        path = private_namespace(connection, subject, context.id) if kind != "service" else None
        result = {"principal": subject}
        if human:
            connection.execute(text("""
              INSERT INTO users(principal_id,email,password_hash)
              VALUES(:id,:email,:hash)
            """), {"id": identity, "email": payload["email"].lower(), "hash": hashed})
        else:
            grants = selected["namespace_grants_template"]
            if selected["name"] == "external-readonly":
                grants = payload.get("namespace_grants", [
                    {"path": item, "access": "read"} for item in payload.get("namespaces", [])
                ])
            if sync:
                grants = [{"path": "org", "access": "write"}]
            for grant in grants:
                target = (grant.get("path") or grant.get("namespace")).replace(
                    "agents.<slug>.private", path or "",
                )
                node = namespace(connection, target)
                if not node:
                    raise ValueError("Template references an unknown namespace")
                connection.execute(text("""
                  INSERT INTO namespace_grants(principal_id,namespace_id,access,granted_by)
                  VALUES(:principal,:namespace,:access,:issuer) ON CONFLICT DO NOTHING
                """), {"principal": identity, "namespace": node["id"],
                       "access": grant.get("access", "read"), "issuer": context.id})
            result["credential"] = mint(connection, context.principal, subject, selected,
                                        payload, service.now())
        if approval_id:
            connection.execute(text("""
              UPDATE approvals SET status='approved',reviewed_by=:reviewer,reviewed_at=:now
              WHERE id=:id AND status='pending'
            """), {"id": approval_id, "reviewer": reviewer, "now": service.now()})
        return result
    decision = {**allow(), **({"template_id": str(selected["id"])} if selected else {})}
    if reviewer:
        decision["reviewer_id"] = str(reviewer)
    return service.perform(context, operation, change=change, decision=decision)


def issue_credential(service, context, payload, approved=False, approval_id=None, reviewer=None):
    with service.engine.connect() as connection:
        target = principal(connection, payload.get("principal_id"))
        selected = template(connection, payload.get("template"))
        decision = evaluate(connection, context, "credentials.issue_sponsored")
        if decision["outcome"] == "ALLOW" and (not target or not selected):
            decision = deny("VALIDATION_FAILED")
        if target and selected and decision["outcome"] == "ALLOW":
            personal = selected["name"].startswith("personal-ai-client")
            if personal and target["kind"] != "human":
                decision = deny("TIER_FORBIDDEN", 3)
            elif context.principal["role"] != "owner" and (
                (personal and target["id"] != context.id)
                or (not personal and target["sponsor_id"] != context.id)
            ):
                decision = deny("SPONSOR_CEILING", 4)
    if decision["outcome"] != "ALLOW":
        return service.record(context, decision, "credentials.issue_sponsored")
    if selected["requires_owner_approval"] and not approved:
        return queue(service, context, "credentials.issue_sponsored", payload, selected)
    trace = {**allow(), "template_id": str(selected["id"])}
    if reviewer:
        trace["reviewer_id"] = str(reviewer)

    def change(connection):
        if approval_id:
            status = connection.execute(text(
                "SELECT status FROM approvals WHERE id=:id FOR UPDATE"
            ), {"id": approval_id}).scalar_one()
            if status != "pending":
                raise ValueError("Approval is no longer pending")
        credential = mint(connection, context.principal, target, selected, payload, service.now())
        if approval_id:
            connection.execute(text("""
              UPDATE approvals SET status='approved',reviewed_at=:now,reviewed_by=:reviewer
              WHERE id=:id
            """), {"id": approval_id, "now": service.now(), "reviewer": reviewer})
        return credential
    return service.perform(context, "credentials.issue_sponsored", decision=trace, change=change)


def update_principal(service, context, identity, payload):
    def preflight(connection):
        subject = principal(connection, identity)
        if subject and subject["kind"] == "agent" and payload.get("tier", subject["tier"]) > 3:
            return deny("AGENT_TIER_LIMIT", 3)
        if subject and "sponsor_id" in payload and subject["kind"] != "human":
            sponsor = principal(connection, payload["sponsor_id"]) if payload["sponsor_id"] else None
            if not sponsor or sponsor["kind"] != "human" or sponsor["status"] != "active":
                return deny("SPONSOR_CEILING", 4)
            if subject["role"] == "external" and sponsor["role"] != "owner":
                return deny("SPONSOR_CEILING", 4)
            if subject["tier"] is not None and subject["tier"] > sponsor["tier"]:
                return deny("SPONSOR_CEILING", 4)

    def change(connection):
        subject = principal(connection, identity)
        if not subject:
            raise ValueError("Unknown principal")
        for field in ("status", "tier", "sponsor_id"):
            if field in payload:
                connection.execute(text(f"UPDATE principals SET {field}=:value WHERE id=:id"),
                                   {"value": payload[field], "id": identity})
        if payload.get("status") == "inactive" and subject["kind"] == "human":
            connection.execute(text("""
              UPDATE principals SET status='suspended' WHERE sponsor_id=:id
            """), {"id": identity})
        if "sponsor_id" in payload and subject["status"] == "suspended":
            sponsor = principal(connection, payload["sponsor_id"])
            if sponsor and sponsor["status"] == "active":
                connection.execute(text("UPDATE principals SET status='active' WHERE id=:id"),
                                   {"id": identity})
        return {"principal": principal(connection, identity)}
    return service.perform(context, "principals.admin", change=change, preflight=preflight)


def grant(service, context, payload, remove=False):
    path = payload["namespace"]
    with service.engine.connect() as connection:
        target = principal(connection, payload["principal_id"])
        node = namespace(connection, path)
        decision = allow()
        human = context.principal
        own_private = path == "people." + human["slug"] + ".private"
        if not target or not node or (
            human["role"] == "owner" and path.startswith("people.")
            and path.endswith(".private") and node["owner_principal_id"] != human["id"]
        ):
            decision = deny("NAMESPACE_FORBIDDEN", 5)
        elif human["role"] != "owner" and not (
            own_private and target["sponsor_id"] == human["id"]
        ):
            decision = deny("TIER_FORBIDDEN", 3)
        elif target["kind"] != "human":
            sponsor = principal(connection, target["sponsor_id"])
            if not sponsor or not can_access(connection, sponsor, path,
                                             payload.get("permission") == "write"):
                decision = deny("SPONSOR_CEILING", 4)
    if decision["outcome"] != "ALLOW":
        return service.record(context, decision, "grants.admin", path)

    def change(connection):
        if remove:
            connection.execute(text("""
              DELETE FROM namespace_grants WHERE principal_id=:id AND namespace_id=:namespace
                AND (:all_access OR access=:access)
            """), {"id": target["id"], "namespace": node["id"],
                   "access": payload.get("permission", "read"),
                   "all_access": "permission" not in payload})
        else:
            connection.execute(text("""
              INSERT INTO namespace_grants(principal_id,namespace_id,access,granted_by)
              VALUES(:id,:namespace,:access,:issuer) ON CONFLICT DO NOTHING
            """), {"id": target["id"], "namespace": node["id"],
                   "access": payload.get("permission", "read"), "issuer": context.id})
        return {"outcome": "ALLOW"}
    return service.perform(context, "grants.admin", path, change=change, decision=decision)
