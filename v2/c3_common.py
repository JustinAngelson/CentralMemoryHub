"""C3 operator plumbing: restricted read-only SQL and native HTTPS administration."""
import getpass
import logging
import os
import re
import warnings
from contextlib import contextmanager

import httpx
import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

ORIGIN = "https://centralmemoryhub.com"
OWNER_SLUG = "justin"
# Reviewed C3 roster, not examples or test fixtures. Never infer elevated scopes.
TEMPLATES = {
    "justin": "personal-ai-client",
    "christine": "personal-ai-client",
    "scott": "personal-ai-client",
    "claude-routine": "openclaw-agent-standard",
    "nix-angelson": "openclaw-agent-standard",
    "jr": "openclaw-agent-standard",
    "tt": "openclaw-agent-standard",
}


class OperatorError(Exception):
    """Fixed, content-free operator failure; never wrap response bodies or URLs."""


def quiet():
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("error", getpass.GetPassWarning)


@contextmanager
def readonly_connection():
    # Never fall back to an admin, migrate, v1, or development URL.
    try:
        parts = conninfo_to_dict(os.environ["CMH_PROD_DATABASE_URL"].replace(
            "postgresql+psycopg://", "postgresql://", 1))
        if parts.get("dbname") != "cmh_v2" or parts.get("user") != "cmh_app":
            raise OperatorError("Read-only connection requires cmh_app on cmh_v2.")
        with psycopg.connect(**parts, row_factory=dict_row, connect_timeout=15) as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            yield conn
    except OperatorError:
        raise
    except Exception:  # noqa: BLE001 — suppress connection strings in driver errors
        raise OperatorError("Read-only database operation failed.") from None


def lookup(conn, slug):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise OperatorError("Invalid principal slug.")
    row = conn.execute("""
        SELECT id,slug,kind,sponsor_id,status FROM principals WHERE slug=%s
    """, (slug,)).fetchone()
    if not row:
        raise OperatorError("Principal not found.")
    return row


def request(client, method, path, **kwargs):
    try:
        response = client.request(method, path, **kwargs)
        if response.status_code not in (200, 201):
            raise OperatorError(f"Native HTTPS operation refused (HTTP {response.status_code}).")
        body = response.json()
        if not isinstance(body, dict) or body.get("outcome") in {"DENY", "QUEUE"}:
            raise OperatorError("Native HTTPS operation did not complete.")
        return body
    except OperatorError:
        raise
    except Exception:  # noqa: BLE001 — suppress credential-bearing HTTP exceptions
        # Do not retry a possibly completed mint after a lost response.
        raise OperatorError(
            "Native HTTPS operation failed; check credentials before retrying."
        ) from None


def https_client():
    return httpx.Client(base_url=ORIGIN, headers={"Origin": ORIGIN}, timeout=30,
                        follow_redirects=False, trust_env=False)


@contextmanager
def owner_session(client, prompt=getpass.getpass, on_logout_failure=None):
    authenticated = False
    try:
        email = prompt("Owner email (hidden): ")
        password = prompt("Owner password (hidden): ")
        try:
            request(client, "POST", "/admin/api/login",
                    json={"email": email, "password": password})
            authenticated = True
        finally:
            del email, password
        identity = request(client, "GET", "/admin/api/whoami")
        if identity.get("principal") != OWNER_SLUG or identity.get("role") != "owner":
            raise OperatorError("An Owner session is required.")
        yield
    finally:
        try:
            if authenticated:
                try:
                    request(client, "POST", "/admin/api/logout")
                except BaseException:
                    if on_logout_failure:
                        on_logout_failure()
                    raise
        finally:
            client.cookies.clear()
