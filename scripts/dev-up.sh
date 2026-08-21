#!/usr/bin/env bash
# Starts DynamoDB Local (Docker), the backend (uvicorn), and the frontend
# (vite) dev servers, detached from the current terminal so they survive an
# SSH session dropping.
#
# Everything stays bound to localhost — access it by SSH-forwarding the
# ports (e.g. `ssh -L 5173:localhost:5173 -L 8000:localhost:8000 <host>`)
# rather than exposing them on the network.
#
# Usage: ./scripts/dev-up.sh
# Stop:  ./scripts/dev-stop.sh
# Logs:  tail -f .run/backend.log .run/frontend.log
#        docker logs -f pappy-dynamodb-local
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
mkdir -p "$RUN_DIR"

DYNAMODB_CONTAINER=pappy-dynamodb-local
DYNAMODB_PORT=8500
export PAPPY_DYNAMODB_ENDPOINT_URL="http://127.0.0.1:$DYNAMODB_PORT"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-local}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-local}"
export AWS_REGION="${AWS_REGION:-us-west-2}"

start_dynamodb() {
    if docker ps --format '{{.Names}}' | grep -qx "$DYNAMODB_CONTAINER"; then
        echo "dynamodb-local already running"
        return
    fi
    if docker ps -a --format '{{.Names}}' | grep -qx "$DYNAMODB_CONTAINER"; then
        echo "==> starting existing dynamodb-local container"
        docker start "$DYNAMODB_CONTAINER" >/dev/null
    else
        echo "==> starting dynamodb-local on http://127.0.0.1:$DYNAMODB_PORT"
        docker run -d --name "$DYNAMODB_CONTAINER" \
            -p "127.0.0.1:$DYNAMODB_PORT:8000" \
            amazon/dynamodb-local >/dev/null
    fi
    echo "==> waiting for dynamodb-local"
    for _ in $(seq 1 30); do
        if curl -s -o /dev/null "http://127.0.0.1:$DYNAMODB_PORT"; then
            break
        fi
        sleep 0.5
    done
    echo "==> ensuring pappy table exists"
    (
        cd "$ROOT_DIR/backend"
        uv run python -c \
            "from pappy.repo.table import create_table_if_not_exists; create_table_if_not_exists()"
    )
}

start_backend() {
    local pid_file="$RUN_DIR/backend.pid"
    if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        echo "backend already running (pid $(cat "$pid_file"))"
        return
    fi
    echo "==> starting backend on http://127.0.0.1:8000"
    (
        cd "$ROOT_DIR/backend"
        setsid nohup env \
            PAPPY_DYNAMODB_ENDPOINT_URL="$PAPPY_DYNAMODB_ENDPOINT_URL" \
            AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
            AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
            AWS_REGION="$AWS_REGION" \
            uv run uvicorn pappy.api.app:app \
            --reload --host 127.0.0.1 --port 8000 \
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

start_dynamodb
start_backend
start_frontend

sleep 1
echo
echo "DynamoDB Local: http://127.0.0.1:$DYNAMODB_PORT"
echo "Backend:        http://127.0.0.1:8000/hello"
echo "Frontend:       http://127.0.0.1:5173"
echo
echo "From your phone, SSH-forward both ports, e.g.:"
echo "  ssh -L 5173:localhost:5173 -L 8000:localhost:8000 $(whoami)@<this-host>"
echo
echo "Logs: tail -f $RUN_DIR/backend.log $RUN_DIR/frontend.log"
echo "      docker logs -f $DYNAMODB_CONTAINER"
echo "Stop: $ROOT_DIR/scripts/dev-stop.sh"
