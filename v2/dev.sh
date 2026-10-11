#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src"
exec .local/cmh-v2-venv/bin/python -m uvicorn \
  cmh.app:create_app --factory --uds .local/cmh-v2.sock --no-access-log
