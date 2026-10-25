#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$ROOT/tasks.env"
umask 077
mkdir -p "$ROOT/agent-tasks/data" "$ROOT/runtime/tasks"
case "${1:-stdio}" in
  stdio) export TASK_AGENT="${2:-cli}"; exec "$TASKS_NODE" "$ROOT/agent-tasks/stdio.mjs" ;;
  dashboard) exec "$TASKS_NODE" "$ROOT/agent-tasks/node_modules/agent-tasks/dist/server.js" --port "$AGENT_TASKS_PORT" --db "$AGENT_TASKS_DB" ;;
  *) echo 'Usage: run-tasks.sh stdio [agent] | dashboard' >&2; exit 2 ;;
esac
