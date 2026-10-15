"""Rolling 24h legacy application-audit counts by UTC hour, plus last-seen times."""
import sys

sys.dont_write_bytecode = True

import json
from datetime import UTC, datetime

import c3_common as common
from c3_reports import legacy_usage


def main():
    common.quiet()
    try:
        with common.readonly_connection() as conn:
            subjects = [common.lookup(conn, slug) for slug in ("legacy-mcp", "legacy-rest")]
            result = legacy_usage(conn, subjects, datetime.now(UTC))
        print(json.dumps(result, default=str))
        return 0
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 — never print driver errors or data
        print("C3 legacy usage report failed; no content displayed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
