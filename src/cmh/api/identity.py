"""Thin JSON adapters; no HTML and no alternative permission pipeline."""

from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy import text
from starlette.responses import JSONResponse

from cmh import audit
from cmh.auth.context import current_context, current_service
from cmh.services import accounts, administration, management


def response(body, success=200):
    outcome = body.get("outcome")
    code = body.get("code", "")
    status = 202 if outcome == "QUEUE" else (403 if outcome == "DENY" else success)
    if outcome == "DENY" and code.startswith("AUTH_"):
        status = 401
    return JSONResponse(jsonable_encoder(body), status_code=status)


def cookie_response(body, value, success=200):
    result = response(body, success)
    if value:
        result.set_cookie("cmh_session", value, secure=True, httponly=True,
                          samesite="strict", path="/admin", max_age=7 * 24 * 3600)
    return result


def identity_router(settings):
    router = APIRouter()

    @router.post("/admin/api/bootstrap")
    async def bootstrap(request: Request):
        raw = request.headers.get("authorization", "")
        supplied = raw[7:] if raw.startswith("Bearer ") else ""
        service, context = current_service.get(), current_context.get()
        body, value = accounts.bootstrap(
            service, await request.json(), supplied, settings.bootstrap_token.get_secret_value(),
            context.request_meta,
        )
        return cookie_response(body, value, 201)

    @router.post("/admin/api/login")
    async def login(request: Request):
        body, value = accounts.login(current_service.get(), await request.json(),
                                     current_context.get().request_meta)
        return cookie_response(body, value)

    @router.post("/admin/api/logout")
    def logout():
        result = response(accounts.logout(current_service.get(), current_context.get()))
        result.delete_cookie("cmh_session", path="/admin", secure=True, httponly=True,
                             samesite="strict")
        return result

    @router.get("/api/whoami")
    @router.get("/admin/api/whoami")
    def whoami():
        return response(current_service.get().whoami(current_context.get()))

    @router.post("/api/access/check")
    async def check(request: Request):
        data = await request.json()
        return response(current_service.get().check(
            current_context.get(), data["operation"], data.get("namespace"),
        ))

    @router.post("/api/principals")
    async def bearer_registration(request: Request):
        return response(management.create_principal(
            current_service.get(), current_context.get(), await request.json(),
        ), 201)

    @router.post("/admin/api/principals")
    async def registration(request: Request):
        return response(management.create_principal(
            current_service.get(), current_context.get(), await request.json(),
        ), 201)

    @router.patch("/admin/api/principals/{identity}")
    async def edit_principal(identity: str, request: Request):
        return response(management.update_principal(
            current_service.get(), current_context.get(), identity, await request.json(),
        ))

    @router.post("/admin/api/namespaces")
    async def namespace(request: Request):
        return response(administration.namespace_create(
            current_service.get(), current_context.get(), await request.json(),
        ), 201)

    @router.post("/admin/api/grants")
    @router.delete("/admin/api/grants")
    async def grants(request: Request):
        return response(management.grant(
            current_service.get(), current_context.get(), await request.json(),
            remove=request.method == "DELETE",
        ), 200 if request.method == "DELETE" else 201)

    @router.patch("/admin/api/templates/{name}")
    async def template(name: str, request: Request):
        return response(administration.template_edit(
            current_service.get(), current_context.get(), name, await request.json(),
        ))

    @router.post("/admin/api/templates")
    async def template_create(request: Request):
        return response(administration.template_create(
            current_service.get(), current_context.get(), await request.json(),
        ), 201)

    @router.post("/admin/api/credentials")
    async def issue(request: Request):
        return response(management.issue_credential(
            current_service.get(), current_context.get(), await request.json(),
        ), 201)

    @router.get("/admin/api/credentials")
    def credentials():
        return response(administration.credential_list(
            current_service.get(), current_context.get(),
        ))

    @router.post("/admin/api/credentials/import")
    async def import_legacy(request: Request):
        return response(administration.import_legacy(
            current_service.get(), current_context.get(), await request.json(),
        ), 201)

    @router.post("/admin/api/credentials/{identity}/revoke")
    async def revoke(identity: str, request: Request):
        raw = await request.body()
        data = await request.json() if raw else {}
        return response(administration.revoke(
            current_service.get(), current_context.get(), identity, data,
        ))

    @router.post("/admin/api/credentials/{identity}/rotate")
    def rotate(identity: str):
        return response(administration.rotate(
            current_service.get(), current_context.get(), identity,
        ), 201)

    @router.post("/admin/api/approvals/{identity}/approve")
    def approve(identity: str):
        return response(administration.approve(
            current_service.get(), current_context.get(), identity,
        ))

    @router.get("/admin/api/approvals")
    def approval_list():
        return response(administration.approval_list(
            current_service.get(), current_context.get(),
        ))

    @router.post("/admin/api/approvals/{identity}/deny")
    def reject_approval(identity: str):
        return response(administration.reject_approval(
            current_service.get(), current_context.get(), identity,
        ))

    @router.get("/api/audit/verify")
    def verify():
        service = current_service.get()
        return response(service.perform(current_context.get(), "audit.read", change=audit.verify))

    @router.get("/api/audit/events")
    def events(request: Request):
        def data(connection):
            filters = []
            params = {}
            for argument, column in (
                ("sponsor_id", "sponsor_id"), ("principal_id", "principal_id"),
                ("outcome", "outcome"), ("namespace", "namespace"),
            ):
                if argument in request.query_params:
                    filters.append(column + "=:" + argument)
                    params[argument] = request.query_params[argument]
            for argument, operator in (("from", ">="), ("to", "<=")):
                if argument in request.query_params:
                    filters.append("occurred_at" + operator + ":" + argument)
                    params[argument] = datetime.fromisoformat(
                        request.query_params[argument],
                    )
            where = " WHERE " + " AND ".join(filters) if filters else ""
            rows = connection.execute(text(
                "SELECT * FROM audit_events" + where + " ORDER BY seq LIMIT 1000"
            ), params).mappings().all()
            return {"events": [dict(row) for row in rows]}
        return response(current_service.get().perform(
            current_context.get(), "audit.read", change=data,
        ))

    return router
