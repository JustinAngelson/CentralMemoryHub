"""Structured logs: no headers, query strings, credential values or tracebacks."""

import json
import logging
import re
from contextvars import ContextVar
from uuid import UUID, uuid4

request_id: ContextVar[str] = ContextVar("cmh_request_id", default="startup")
_SENSITIVE = re.compile(r"authorization|token|secret|key|password", re.IGNORECASE)
_BEARER = re.compile(r"\bBearer\s+[^\s\"',;]+", re.IGNORECASE)
_QUERY = re.compile(r"\?[^\s\"']+")
_CREDENTIAL = re.compile(r"cmh_(?:ak|pk|at)_[A-Za-z0-9_-]+")
_SESSION = re.compile(r"cmh_session=[^;\s\"']+")
_secret_values: tuple[str, ...] = ()
_installed = False
_STANDARD_FIELDS = set(logging.makeLogRecord({}).__dict__) | {
    "message", "asctime", "requestID"
}


def redact(value, field: str = ""):
    if _SENSITIVE.search(field):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(key): redact(item, str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = _BEARER.sub("Bearer [REDACTED]", value)
        value = _QUERY.sub("?[REDACTED]", value)
        value = _CREDENTIAL.sub("[REDACTED]", value)
        value = _SESSION.sub("cmh_session=[REDACTED]", value)
        for secret in _secret_values:
            value = value.replace(secret, "[REDACTED]")
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(str(value))


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        for key, value in list(record.__dict__.items()):
            if key not in _STANDARD_FIELDS:
                setattr(record, key, redact(value, key))
        return True


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        result = {
            "level": record.levelname,
            "logger": record.name,
            "event": redact(record.getMessage()),
            "requestID": getattr(record, "requestID", request_id.get()),
        }
        result.update({
            key: redact(value, key)
            for key, value in record.__dict__.items()
            if key not in _STANDARD_FIELDS
        })
        if record.exc_info:
            result["exception_type"] = record.exc_info[0].__name__
        return json.dumps(result, default=str)


def configure_logging(sensitive_values: tuple[str, ...]) -> None:
    global _installed, _secret_values
    _secret_values = tuple(value for value in sensitive_values if value)
    logging.captureWarnings(True)
    # Uvicorn's CLI flag only clears handlers/propagation before loading the
    # factory. Explicitly disable this logger so later root logging cannot
    # bring back credential-bearing URLs or query strings.
    access = logging.getLogger("uvicorn.access")
    access.disabled = True
    access.handlers.clear()
    access.propagate = False
    if not _installed:
        previous = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            record = previous(*args, **kwargs)
            record.requestID = request_id.get()
            record.msg = redact(record.getMessage())
            record.args = ()
            return record

        logging.setLogRecordFactory(factory)
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredFormatter())
        handler.addFilter(RedactionFilter())
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("cmh").addFilter(RedactionFilter())
        for name in ("uvicorn", "uvicorn.error"):
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.propagate = True
        _installed = True


class RequestIDMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            identifier = str(UUID(headers.get(b"x-request-id", b"").decode("ascii")))
        except (ValueError, UnicodeError):
            identifier = str(uuid4())
        context = request_id.set(identifier)
        status = 500

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []), (b"x-request-id", identifier.encode("ascii"))
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            logging.getLogger("cmh").info(
                "request_complete", extra={"method": scope["method"], "status": status}
            )
            request_id.reset(context)
