#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Old lifecycle spelling stays valid: ./cli.sh tasks status
if [ "${1:-}" = tasks ]; then shift; set -- "${1:-status}" tasks; fi
exec "$ROOT/.venv/bin/python" "$ROOT/scripts/manage.py" "${@:-status}"
