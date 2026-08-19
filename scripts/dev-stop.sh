#!/usr/bin/env bash
# Stops servers started by dev-up.sh.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"

stop_one() {
    local name="$1"
    local pid_file="$RUN_DIR/$name.pid"
    if [ ! -f "$pid_file" ]; then
        echo "$name: not running (no pid file)"
        return
    fi
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
        # setsid gave each process its own group; kill the whole group so
        # `npm run dev`'s child (vite) dies too, not just the npm wrapper.
        kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
        echo "$name: stopped (pid $pid)"
    else
        echo "$name: not running (stale pid $pid)"
    fi
    rm -f "$pid_file"
}

stop_one backend
stop_one frontend
