"""Test-body-only audit gate. Never counts setup events or removes audit rows."""

import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps

import httpx
import pytest
from sqlalchemy import text

ACTIVE_BODY = None


def is_health_probe(request):
    return request.method == "GET" and request.url.raw_path == b"/healthz"


def service_profile(frame, event, arg):
    if (
        ACTIVE_BODY is not None and event == "call"
        and frame.f_globals.get("__name__", "").startswith("cmh.services")
    ):
        ACTIVE_BODY.services += 1


@dataclass
class BodyActivity:
    requests: int = 0
    services: int = 0


def validate_exemption(marker, activity):
    if marker is None:
        return
    reason = marker.kwargs.get("reason")
    if marker.args or not isinstance(reason, str) or not reason.strip():
        pytest.fail("no_app_operation requires a non-empty keyword reason")
    if activity.requests or activity.services:
        pytest.fail("no_app_operation hid an HTTP request or services-layer call")


def highest_seq(engine):
    with engine.connect() as connection:
        exists = connection.execute(text("SELECT to_regclass('public.audit_events')")).scalar()
        if exists is None:
            return 0
        return connection.execute(text(
            "SELECT COALESCE(MAX(seq), 0) FROM audit_events"
        )).scalar_one()


@contextmanager
def observe_body():
    global ACTIVE_BODY

    activity = BodyActivity()
    old_sys = sys.getprofile()
    old_threads = threading.getprofile()

    with pytest.MonkeyPatch.context() as patch:
        for owner in (httpx.Client, httpx.AsyncClient):
            original = owner.send

            if owner is httpx.AsyncClient:
                def async_wrapper(method):
                    @wraps(method)
                    async def wrapped(*args, **kwargs):
                        if not is_health_probe(args[1]):
                            activity.requests += 1
                        return await method(*args, **kwargs)
                    return wrapped
                patch.setattr(owner, "send", async_wrapper(original))
            else:
                def sync_wrapper(method):
                    @wraps(method)
                    def wrapped(*args, **kwargs):
                        if not is_health_probe(args[1]):
                            activity.requests += 1
                        return method(*args, **kwargs)
                    return wrapped
                patch.setattr(owner, "send", sync_wrapper(original))
        ACTIVE_BODY = activity
        sys.setprofile(service_profile)
        threading.setprofile(service_profile)
        try:
            yield activity
        finally:
            sys.setprofile(old_sys)
            threading.setprofile(old_threads)
            ACTIVE_BODY = None
