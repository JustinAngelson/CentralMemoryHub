"""Per-request immutable authentication state. Never contains token plaintext."""

from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass(frozen=True, repr=False)
class PrincipalContext:
    principal: dict
    credential: dict | None = None
    session_hash: str | None = None
    request_meta: dict = field(default_factory=dict)

    @property
    def actor(self):
        return self.credential["name"] if self.credential else self.principal.get(
            "slug", "unauthenticated",
        )

    @property
    def id(self):
        return self.principal["id"]


current_context = ContextVar("cmh_principal_context", default=None)
current_service = ContextVar("cmh_request_service", default=None)
