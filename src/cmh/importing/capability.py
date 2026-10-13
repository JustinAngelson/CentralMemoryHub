"""In-process import capabilities. No request adapter accepts or constructs these."""
from dataclasses import dataclass, field

_SEAL = object()


@dataclass(frozen=True)
class ImportRecord:
    author: object
    created_at: object
    updated_at: object
    trace: dict
    seal: object = field(default=None, repr=False)

    def validate(self, context):
        if (self.seal is not _SEAL or context.principal.get("kind") != "service"
            or context.principal.get("slug") != "v1-import"
            or context.request_meta.get("surface") != "import"):
            raise ValueError("Import capability is not available on request surfaces")


def import_record(author, created_at, updated_at, trace):
    return ImportRecord(author, created_at, updated_at, trace, _SEAL)


@dataclass(frozen=True)
class RosterSpec:
    row: dict
    seal: object = field(default=None, repr=False)

    def validate(self, context):
        if (self.seal is not _SEAL or context.principal.get("role") != "owner"
            or context.request_meta.get("surface") != "import"):
            raise ValueError("Roster import requires native Owner administration")


def roster_spec(row):
    return RosterSpec(row, _SEAL)
