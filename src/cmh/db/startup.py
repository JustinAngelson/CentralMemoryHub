"""Offline, fail-closed workspace/production boundary, before engine creation."""

import os
import re

from sqlalchemy.engine import make_url

# These libpq parameters can override the URL authority/database. Refuse rather
# than guessing which server would actually receive a connection.
_ROUTING_PARAMETERS = {"host", "hostaddr", "port", "dbname", "database", "service", "servicefile"}


def _target(value, reason):
    try:
        url = make_url(value)
        if (
            url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}
            or not url.host or not url.database
            or not re.fullmatch(r"[A-Za-z0-9.:-]+", url.host)
            or _ROUTING_PARAMETERS.intersection(key.lower() for key in url.query)
        ):
            raise ValueError
        # Neon direct and pooled endpoints identify the same production server.
        host = url.host.lower().rstrip(".")
        labels = host.split(".")
        if host.endswith(".neon.tech") and labels[0].endswith("-pooler"):
            labels[0] = labels[0][:-len("-pooler")]
            host = ".".join(labels)
        # Credentials and connection options never participate in identity.
        return host, url.database
    except Exception:  # noqa: BLE001 — fixed reason only, never a URL/driver error
        raise RuntimeError(reason) from None


def guard_database_target(database_url, environment, *, environ=None):
    """A published-runtime marker, not CMH_ENV, authorizes a production target.

    REPLIT_DEPLOYMENT is '1' in a published runtime and absent in the workspace.
    Any other value is unknown and refused. No connections or logging occur.
    """
    env = os.environ if environ is None else environ
    deployment = env.get("REPLIT_DEPLOYMENT")
    if deployment not in {None, "1"}:
        raise RuntimeError("Unknown deployment environment")
    if environment not in {"dev", "test", "prod"}:
        raise RuntimeError("Unknown application environment")
    target = _target(database_url, "Invalid database target")
    if deployment == "1":
        return
    reference = env.get("CMH_PROD_DATABASE_URL")
    if reference is not None:
        production = _target(reference, "Invalid production database reference")
        if target == production:
            raise RuntimeError("Production database forbidden outside deployment")
    # The operator-only reference secret may be removed from Publishing or the
    # workspace. A production-named Neon target is still forbidden without it.
    if target[0].endswith(".neon.tech") and target[1] == "cmh_v2":
        raise RuntimeError("Production database forbidden outside deployment")
