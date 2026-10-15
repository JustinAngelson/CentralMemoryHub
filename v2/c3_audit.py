"""Last ten audit events for a principal; no content, trace bodies or token material."""
import sys

sys.dont_write_bytecode = True

import argparse
import json

import c3_common as common
from c3_reports import audit_events, parse_since


def main(argv=None):
    common.quiet()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("principal_slug")
    parser.add_argument("--since", help="ISO-8601 timestamp with timezone")
    args = parser.parse_args(argv)
    try:
        since = parse_since(args.since)
        with common.readonly_connection() as conn:
            subject = common.lookup(conn, args.principal_slug)
            events = audit_events(conn, subject["id"], since)
        print(json.dumps(events, default=str))
        return 0
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 — never print driver errors or data
        print("C3 audit report failed; no content displayed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
