"""Static compatibility landing and bounded waitlist; no signup details enter audit/logs."""
import hashlib
import hmac
import json
import re
import unicodedata
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from sqlalchemy import text
from starlette.responses import HTMLResponse, JSONResponse

from cmh import audit
from cmh.auth.context import current_context
from cmh.policy.evaluator import allow

EMAIL = re.compile(r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*@"
                   r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def public_router(identity, settings):
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def landing():
        return HTMLResponse((Path(__file__).parents[1] / "public" / "landing.html").read_text())

    @router.post("/api/waitlist")
    async def waitlist(request: Request):
        context = current_context.get()
        data, valid = {}, True
        try:
            if "application/json" not in request.headers.get("content-type", ""):
                raise ValueError()
            content = bytearray()
            async for chunk in request.stream():
                content.extend(chunk)
                if len(content) > 2048:
                    raise ValueError()
            data = json.loads(content)
            if not isinstance(data, dict):
                raise TypeError()
            name, email = data.get("first_name"), data.get("email")
            if not isinstance(name, str) or not isinstance(email, str):
                raise TypeError()
            if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in name + email):
                raise ValueError()
            name, email = name.strip(), email.strip().casefold()
            if (not 1 <= len(name) <= 100 or not 1 <= len(email) <= 120
                or len(email.split("@")[0]) > 64 or not EMAIL.fullmatch(email)):
                raise ValueError()
        except (ValueError, UnicodeError, TypeError):
            valid = False
        now = identity.now()
        ip_hash = hmac.new(settings.bootstrap_token.get_secret_value().encode(),
                           context.request_meta["client_ip"].encode(), hashlib.sha256).hexdigest()
        with identity.engine.begin() as conn:
            # Across workers, rate admission, duplicate detection and daily capacity
            # share one bounded transaction. Append the content-free counter last.
            conn.execute(text("SET LOCAL lock_timeout='5s'"))
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('cmh.waitlist'))"))
            conn.execute(text("DELETE FROM waitlist_attempts WHERE attempted_at<=:start"),
                         {"start": now - timedelta(hours=1)})
            attempts = conn.execute(text("""SELECT count(*) FROM waitlist_attempts
              WHERE ip_hash=:ip AND attempted_at>:start"""),
                                    {"ip": ip_hash, "start": now - timedelta(hours=1)}).scalar_one()
            if attempts < 5:
                conn.execute(text("INSERT INTO waitlist_attempts VALUES(:ip,:now)"), {"ip": ip_hash, "now": now})
            status, body = 200, {"ok": True, "message": "Thanks for joining the waitlist."}
            if attempts >= 5:
                status, body = 429, {"ok": False, "error": "Please try again later"}
            elif not valid:
                status, body = 400, {"ok": False, "error": "Enter a valid name and email (maximum 120 characters)"}
            elif not data.get("website"):
                duplicate = conn.execute(text("SELECT 1 FROM waitlist WHERE lower(email)=:email"),
                                         {"email": email}).scalar()
                count = conn.execute(text("SELECT count(*) FROM waitlist WHERE created_at>=:start"),
                                     {"start": now.replace(hour=0, minute=0, second=0, microsecond=0)}).scalar_one()
                if not duplicate and count >= 200:
                    status, body = 429, {"ok": False, "error": "Please try again later"}
                elif not duplicate:
                    conn.execute(text("""INSERT INTO waitlist(email,first_name,created_at,source)
                      VALUES(:email,:name,:now,'v2')"""), {"email": email, "name": name, "now": now})
                    # Only an accepted new signup is an application mutation.
                    audit.append(conn, context, {**allow(), "counter": {"waitlist_requests": 1}},
                                 "public.waitlist.counter", now)
        return JSONResponse(body, status_code=status)

    return router


class PublicSecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def secure(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([(b"x-frame-options", b"DENY"),
                                (b"x-content-type-options", b"nosniff"),
                                (b"content-security-policy",
                                 b"frame-ancestors 'none'; object-src 'none'; base-uri 'self'")])
                message = {**message, "headers": headers}
            await send(message)
        await self.app(scope, receive, secure)
