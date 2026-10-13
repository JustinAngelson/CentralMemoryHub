"""Private snapshot review CLI. No target mutation before review approval."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cmh.importing.plan import build_plan, load_orgs, require_review_files, write_plan
from cmh.importing.source import connection_from_env, read_source, target_state


def private_output_directory(value):
    directory = Path(value).resolve()
    repository = Path(__file__).resolve().parents[1]
    if directory.name != "cmh-v2-import" or directory.parent.name != ".local":
        raise ValueError("Review output must use the private .local/cmh-v2-import directory")
    if directory.is_relative_to(repository) and directory.relative_to(repository).parts[0] != ".local":
        raise ValueError("Review output must not be in public tracked directories")
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare private v1 import review files")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--plan", action="store_true")
    modes.add_argument("--apply", action="store_true")
    parser.add_argument("--source-env", default="CMH_TEST_DATABASE_URL")
    parser.add_argument("--source-database", default="cmh_v1_snapshot")
    parser.add_argument("--target-database", default="cmh_v2_import")
    parser.add_argument("--defaults", type=Path, required=True)
    parser.add_argument("--orgs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        args.out = private_output_directory(args.out)
        if args.apply:
            require_review_files(args.out)
            raise ValueError("Apply is gated pending owner review; this checkpoint is plan-only")
        source = connection_from_env(args.source_env, args.source_database)
        # Whole-table proof cannot use an RLS-filtered app/migration view.
        # The isolated test administrator still explicitly sets READ ONLY.
        target = connection_from_env("CMH_TEST_DATABASE_URL", args.target_database)
        before = target_state(target)
        plan = build_plan(read_source(source), json.loads(args.defaults.read_text()),
                          load_orgs(args.orgs))
        after = target_state(target)
        if before != after:
            raise ValueError("Target changed while planning; do not rely on these proposals")
        write_plan(plan, args.out)
        # Metadata only. Never output values, credentials, content or checksums.
        proof = args.out / "plan-target-proof.json"
        proof.write_text(json.dumps({"before": before, "after": after,
                                     "unchanged": True, "embeddings": 0}, indent=2))
        proof.chmod(0o600)
        print(json.dumps({"mode": "plan", "target_unchanged": True,
                          "source_rows": plan["source_total"],
                          "roster_rows": len(plan["roster"]),
                          "attribution_rows": len(plan["attribution"]),
                          "namespace_rows": len(plan["namespaces"]),
                          "embeddings": 0}))
        return 0
    except Exception as exc:  # noqa: BLE001 — credential-safe CLI boundary
        # Exception representations/tracebacks can contain connection secrets.
        print(json.dumps({"mode": "plan" if args.plan else "apply",
                          "status": "failed", "error_type": type(exc).__name__}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
