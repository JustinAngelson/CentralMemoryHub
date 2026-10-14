"""One-shot legacy handoff. Never invoke from startup or from tests with real secrets."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

def main(argv=None):
    # Load sibling explicitly: stdlib operator must never be shadowed at Python startup.
    import importlib.util

    from cmh.cutover.legacy import load_legacy

    spec = importlib.util.spec_from_file_location("cutover_operator", Path(__file__).with_name("cutover_operator.py"))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    args = helper.arguments("One-shot legacy credential import").parse_args(argv)
    engine = None
    try:
        engine, service, owner = helper.connect(args)
        print(json.dumps({"credentials": load_legacy(service, owner, os.environ)}))
        return 0
    except Exception as error:  # noqa: BLE001 — never leak credential-bearing exceptions
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
