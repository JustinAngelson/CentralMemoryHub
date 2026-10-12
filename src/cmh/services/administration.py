"""Owner governance, approval review and credential lifecycle."""

import json
import re
import secrets
from datetime import timedelta

from sqlalchemy import text

from cmh.auth.context import PrincipalContext
from cmh.policy.evaluator import deny, evaluate, principal
from cmh.policy.scopes import envelope
from cmh.services.accounts import digest
from cmh.services.management import create_principal, issue_credential


def namespace_create(service, context, payload):
    def preflight(connection):
        path = payload.get("path", "")
        if not re.fullmatch(r"(?:org|people)(?:\.[a-zA-Z0-9_-]+)+", path):
            return deny("NAMESPACE_FORBIDDEN", 5)

    def change(connection):
        row = connection.execute(text("""
          INSERT INTO namespaces(path,description,mode,created_by,owner_principal_id)
          VALUES(CAST(:path AS ltree),:description,:mode,:creator,:owner) RETURNING *
        """), {"path": payload["path"], "description": payload.get("description", ""),
               "mode": payload.get("mode", "flag"), "creator": context.id,
               "owner": payload.get("owner_principal_id")}).mappings().one()
        return {"namespace": dict(row)}
    return service.perform(context, "principals.admin", change=change, preflight=preflight)


def template_edit(service, context, name, payload):
    def change(connection):
        allowed = {
            "scopes", "target_role", "target_tier", "namespace_grants_template",
            "default_expiry_days", "requires_owner_approval", "active",
        }
        for field in allowed & payload.keys():
            value = payload[field]
            if field == "namespace_grants_template":
                value = json.dumps(value)
            connection.execute(text(
                f"UPDATE credential_templates SET {field}="
                + ("CAST(:value AS jsonb)" if field == "namespace_grants_template" else ":value")
                + " WHERE name=:name"
            ), {"value": value, "name": name})
        return {"outcome": "ALLOW"}
    return service.perform(context, "credentials.admin", change=change)


def import_legacy(service, context, payload):
    def change(connection):
        subject = principal(connection, payload["principal_id"])
        row = connection.execute(text("""
          INSERT INTO credentials(principal_id,token_hash,token_prefix,name,kind,
            ai_client,scopes,issued_by,created_at)
          VALUES(:principal,:hash,:prefix,:name,'legacy_shared',false,:scopes,:issuer,:now)
          RETURNING id,name,token_prefix
        """), {"principal": subject["id"], "hash": digest(payload["token"]),
               "prefix": payload["token"][:4], "name": payload["name"],
               "scopes": sorted(envelope(subject)), "issuer": context.id,
               "now": service.now()}).mappings().one()
        return dict(row)
    return service.perform(context, "credentials.admin", change=change)


def revoke(service, context, identity, payload):
    def change(connection):
        connection.execute(text("""
          UPDATE credentials SET revoked_at=:now,revoked_by=:actor,revoke_reason=:reason
          WHERE id=:id
        """), {"id": identity, "now": service.now(), "actor": context.id,
               "reason": payload.get("reason", "Owner revoked")})
        return {"outcome": "ALLOW"}
    return service.perform(context, "credentials.admin", change=change)


def rotate(service, context, identity):
    def change(connection):
        old = connection.execute(text(
            "SELECT * FROM credentials WHERE id=:id FOR UPDATE"
        ), {"id": identity}).mappings().one()
        now = service.now()
        prefix = {"api": "cmh_ak_", "personal_ai_client": "cmh_pk_", "legacy_shared": ""}[old["kind"]]
        value = prefix + secrets.token_urlsafe(32)
        row = connection.execute(text("""
          INSERT INTO credentials(principal_id,token_hash,token_prefix,name,kind,client_label,
            ai_client,scopes,template_id,issued_by,created_at,expires_at,rate_limit)
          VALUES(:principal,:hash,:prefix,:name,:kind,:label,:ai,:scopes,:template,
            :issuer,:now,:expires,:limit)
          RETURNING id,principal_id,name,kind,scopes,token_prefix,template_id
        """), {"principal": old["principal_id"], "hash": digest(value), "prefix": value[:11],
               "name": old["name"], "kind": old["kind"], "label": old["client_label"],
               "ai": old["ai_client"], "scopes": old["scopes"], "template": old["template_id"],
               "issuer": context.id, "now": now, "expires": now + timedelta(days=90),
               "limit": old["rate_limit"]}).mappings().one()
        expiry = min(now + timedelta(hours=24), old["expires_at"]) if old["expires_at"] else (
            now + timedelta(hours=24)
        )
        connection.execute(text("UPDATE credentials SET expires_at=:at WHERE id=:id"),
                           {"at": expiry, "id": identity})
        return {**row, "token": value}
    return service.perform(context, "credentials.admin", change=change)


def credential_list(service, context):
    def data(connection):
        return {"credentials": [dict(row) for row in connection.execute(text("""
          SELECT id,principal_id,token_prefix,name,kind,client_label,ai_client,scopes,
            template_id,issued_by,created_at,expires_at,last_used_at,revoked_at,rate_limit
          FROM credentials ORDER BY created_at,id
        """)).mappings()]}
    return service.perform(context, "credentials.admin", change=data)


def approve(service, context, identity):
    with service.engine.begin() as connection:
        decision = evaluate(connection, context, "approvals.review")
        if context.principal["role"] != "owner":
            decision = deny("TIER_FORBIDDEN", 3)
        row = connection.execute(text(
            "SELECT * FROM approvals WHERE id=:id FOR UPDATE"
        ), {"id": identity}).mappings().first()
        if not row:
            decision = deny("APPROVAL_NOT_FOUND")
        elif row["status"] != "pending":
            decision = deny("APPROVAL_NOT_PENDING")
        elif row["expires_at"] <= service.now():
            connection.execute(text("UPDATE approvals SET status='expired' WHERE id=:id"),
                               {"id": identity})
            decision = deny("APPROVAL_EXPIRED")
        requester = principal(connection, row["requester_id"]) if row else None
    if decision["outcome"] != "ALLOW":
        return service.record(context, decision, "approvals.review")
    if not requester or requester["status"] != "active":
        return service.record(context, deny("PRINCIPAL_INACTIVE"), "approvals.review")
    requested_context = PrincipalContext(
        requester, request_meta={**context.request_meta, "reviewer_id": str(context.id)},
    )
    if row["payload"].get("slug"):
        return create_principal(service, requested_context, row["payload"], approved=True,
                                approval_id=identity, reviewer=context.id)
    # Credential approval uses the same issuer checks and template evaluation.
    return issue_credential(service, requested_context, row["payload"], approved=True,
                            approval_id=identity, reviewer=context.id)


def approval_list(service, context):
    def data(connection):
        connection.execute(text("""
          UPDATE approvals SET status='expired'
          WHERE required_reviewer_id=:id AND status='pending' AND expires_at <= :now
        """), {"id": context.id, "now": service.now()})
        rows = connection.execute(text("""
          SELECT id,requester_id,required_reviewer_id,operation,payload,status,created_at,
            expires_at,reviewed_at,reviewed_by FROM approvals
          WHERE required_reviewer_id=:id ORDER BY created_at,id
        """), {"id": context.id}).mappings().all()
        return {"approvals": [dict(row) for row in rows]}
    return service.perform(context, "approvals.review", change=data)


def reject_approval(service, context, identity):
    def preflight(connection):
        row = connection.execute(text("SELECT * FROM approvals WHERE id=:id FOR UPDATE"),
                                 {"id": identity}).mappings().first()
        if not row or row["required_reviewer_id"] != context.id or row["status"] != "pending":
            return deny("APPROVAL_NOT_PENDING")

    def change(connection):
        connection.execute(text("""
          UPDATE approvals SET status='denied',reviewed_at=:now,reviewed_by=:reviewer WHERE id=:id
        """), {"id": identity, "now": service.now(), "reviewer": context.id})
        return {"outcome": "ALLOW"}
    return service.perform(context, "approvals.review", change=change, preflight=preflight)


def template_create(service, context, payload):
    def change(connection):
        row = connection.execute(text("""
          INSERT INTO credential_templates(name,target_role,target_tier,scopes,
            namespace_grants_template,default_expiry_days,requires_owner_approval,created_by)
          VALUES(:name,:role,:tier,:scopes,CAST(:grants AS jsonb),:days,:approval,:creator)
          RETURNING *
        """), {"name": payload["name"], "role": payload.get("target_role"),
               "tier": payload.get("target_tier"), "scopes": payload["scopes"],
               "grants": json.dumps(payload.get("namespace_grants_template", [])),
               "days": payload.get("default_expiry_days", 90),
               "approval": payload.get("requires_owner_approval", False),
               "creator": context.id}).mappings().one()
        return {"template": dict(row)}
    return service.perform(context, "credentials.admin", change=change)
