"""Private rollback export; no writes to the database, emails or credential values."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def validate_export(path, since):
    path = path.resolve()
    if ".local" not in path.parts or path.suffix != ".json":
        raise ValueError("Export must be private JSON under .local")
    timestamp = datetime.fromisoformat(since)
    if timestamp.tzinfo is None:
        raise ValueError("A timezone-aware --since is required")
    return path, timestamp


def main(argv=None):
    import importlib.util

    from cmh.cutover.exporting import export_records

    spec = importlib.util.spec_from_file_location("cutover_operator", Path(__file__).with_name("cutover_operator.py"))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    parser = helper.arguments("Read-only rollback export")
    parser.add_argument("--since", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    engine = None
    try:
        path, since = validate_export(args.out, args.since)
        engine, _, owner = helper.connect(args)
        with engine.connect() as connection:
            records, counts = export_records(connection, since, owner)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump({"since": since.isoformat(), "records": records, "counts": counts}, handle,
                      default=str)
        print(json.dumps({"status": "exported", "counts": counts}))
        return 0
    except Exception as error:  # noqa: BLE001 — never leak credential-bearing exceptions
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
