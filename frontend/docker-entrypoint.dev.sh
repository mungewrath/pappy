#!/bin/sh
# Frontend dev entrypoint: keeps the node_modules volume in sync with
# package.json/package-lock.json. The image bakes node_modules in along with
# a stamp hash; if the mounted manifests no longer match (e.g. you added a
# dependency on the host), re-run npm ci inside the container's volume so the
# app starts with the right deps. No rebuild needed for source changes.
set -eu

stamp="node_modules/.pappy-install-stamp"
current="$(cat package.json package-lock.json | sha256sum | cut -d' ' -f1)"
saved="$(cat "$stamp" 2>/dev/null || true)"

if [ "$current" != "$saved" ]; then
    echo "==> dependencies changed; running npm ci..."
    npm ci --no-audit --no-fund
    printf '%s\n' "$current" >"$stamp"
fi

exec "$@"
