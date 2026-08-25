#!/usr/bin/env bash
# Builds the SPA with the deployed backend's config baked in, applies
# Terraform to upload it, and seeds the rate tables. This exists because
# `VITE_*` vars are read at *build* time, not runtime — a `npm run build`
# without them (or a stale `.env.local`) silently ships a bundle with no API
# URL / no Cognito config, which is exactly the failure mode this script is
# meant to prevent.
#
# Rate tables (`rates/*.json`) are data in DynamoDB, not code (design-doc §5.2),
# so they must be loaded out-of-band: finalization 404s without them. Seeding
# runs after apply so the table exists on a first deploy, and is idempotent
# (`put_if_absent`) — re-runs and new tax-year files are both handled by
# simply deploying again. Uses ambient AWS credentials: AWS_PROFILE locally,
# OIDC session vars in GitHub Actions.
#
# Usage: AWS_PROFILE=pappy ./scripts/deploy.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> reading current infra config from terraform output"
cd "$ROOT_DIR/terraform"
API_BASE_URL="$(terraform output -raw api_invoke_url)"
COGNITO_USER_POOL_ID="$(terraform output -raw cognito_user_pool_id)"
COGNITO_CLIENT_ID="$(terraform output -raw cognito_user_pool_client_id)"
COGNITO_DOMAIN="$(terraform output -raw cognito_hosted_ui_domain)"
COGNITO_REGION="$(terraform output -raw cognito_user_pool_id | cut -d_ -f1)"

# API Gateway's invoke_url has a trailing slash; the frontend appends paths
# starting with "/", so strip it to avoid a double slash.
API_BASE_URL="${API_BASE_URL%/}"

echo "    VITE_API_BASE_URL=$API_BASE_URL"
echo "    VITE_COGNITO_USER_POOL_ID=$COGNITO_USER_POOL_ID"
echo "    VITE_COGNITO_CLIENT_ID=$COGNITO_CLIENT_ID"
echo "    VITE_COGNITO_DOMAIN=$COGNITO_DOMAIN"
echo "    VITE_COGNITO_REGION=$COGNITO_REGION"

echo "==> building frontend"
cd "$ROOT_DIR/frontend"
VITE_API_BASE_URL="$API_BASE_URL" \
VITE_COGNITO_USER_POOL_ID="$COGNITO_USER_POOL_ID" \
VITE_COGNITO_CLIENT_ID="$COGNITO_CLIENT_ID" \
VITE_COGNITO_DOMAIN="$COGNITO_DOMAIN" \
VITE_COGNITO_REGION="$COGNITO_REGION" \
    npm run build

echo "==> applying terraform (uploads frontend/dist, no-op elsewhere unless .tf files changed)"
cd "$ROOT_DIR/terraform"
terraform apply "$@"

echo "==> seeding rate tables"
TABLE_NAME="$(terraform output -raw dynamodb_table_name)"
echo "    table=$TABLE_NAME"
cd "$ROOT_DIR/backend"
PAPPY_TABLE_NAME="$TABLE_NAME" PAPPY_RATES_DIR="$ROOT_DIR/rates" \
    uv run python -m pappy.repo.seed
