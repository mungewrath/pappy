#!/usr/bin/env bash
# Builds the Lambda deployment artifact for the API function.
#
# Per the design doc (§2.4), packaging happens outside Terraform: dependencies
# are exported and installed for linux/aarch64, the app is added on top, and
# the result is zipped. Terraform consumes the resulting object key/version as
# a variable rather than building anything itself.
#
# Usage: ./build.sh [output-dir]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${1:-$SCRIPT_DIR/dist}"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT

mkdir -p "$OUT_DIR"

echo "==> Exporting pinned dependencies"
uv export \
    --project "$SCRIPT_DIR" \
    --no-dev \
    --no-hashes \
    --format requirements-txt \
    -o "$BUILD_DIR/requirements.txt"

echo "==> Installing dependencies for linux/aarch64 (Python 3.13)"
uv pip install \
    --python-platform aarch64-unknown-linux-gnu \
    --python 3.13 \
    --target "$BUILD_DIR/package" \
    -r "$BUILD_DIR/requirements.txt"

echo "==> Adding application code"
cp -r "$SCRIPT_DIR/pappy" "$BUILD_DIR/package/"

echo "==> Zipping artifact"
ARTIFACT="$OUT_DIR/api-lambda.zip"
rm -f "$ARTIFACT"
# Use Python's zipfile rather than the system `zip` binary, which isn't
# guaranteed to be installed. Deterministic file order keeps rebuilds
# reproducible when nothing actually changed.
python3 - "$BUILD_DIR/package" "$ARTIFACT" <<'PYEOF'
import pathlib
import sys
import zipfile

src, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(src.rglob("*")):
        if path.is_file():
            zf.write(path, path.relative_to(src))
PYEOF

echo "==> Built $ARTIFACT"
