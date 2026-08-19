#!/usr/bin/env bash
# Starts the backend (uvicorn) and frontend (vite) dev servers, detached from
# the current terminal so they survive an SSH session dropping.
#
# Both stay bound to localhost — access them by SSH-forwarding the ports
# (e.g. `ssh -L 5173:localhost:5173 -L 8000:localhost:8000 <host>`) rather
# than exposing them on the network.
#
# Usage: ./scripts/dev-up.sh
# Stop:  ./scripts/dev-stop.sh
# Logs:  tail -f .run/backend.log .run/frontend.log
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
mkdir -p "$RUN_DIR"

start_backend() {
    local pid_file="$RUN_DIR/backend.pid"
    if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        echo "backend already running (pid $(cat "$pid_file"))"
        return
    fi
    echo "==> starting backend on http://127.0.0.1:8000"
    (
        cd "$ROOT_DIR/backend"
        setsid nohup uv run uvicorn pappy.api.app:app \
            --host 127.0.0.1 --port 8000 \
            >"$RUN_DIR/backend.log" 2>&1 &
        echo $! >"$pid_file"
    )
}

start_frontend() {
    local pid_file="$RUN_DIR/frontend.pid"
    if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        echo "frontend already running (pid $(cat "$pid_file"))"
        return
    fi
    echo "==> starting frontend on http://127.0.0.1:5173"
    (
        cd "$ROOT_DIR/frontend"
        setsid nohup npm run dev -- --host 127.0.0.1 --port 5173 \
            >"$RUN_DIR/frontend.log" 2>&1 &
        echo $! >"$pid_file"
    )
}

start_backend
start_frontend

sleep 1
echo
echo "Backend:  http://127.0.0.1:8000/hello"
echo "Frontend: http://127.0.0.1:5173"
echo
echo "From your phone, SSH-forward both ports, e.g.:"
echo "  ssh -L 5173:localhost:5173 -L 8000:localhost:8000 $(whoami)@<this-host>"
echo
echo "Logs: tail -f $RUN_DIR/backend.log $RUN_DIR/frontend.log"
echo "Stop: $ROOT_DIR/scripts/dev-stop.sh"
