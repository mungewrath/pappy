# Pappy frontend

React + Vite SPA (§2.2, §2.4 of the design doc). Static bundle, deployed to
S3 + CloudFront; runs against a local backend during development.

## Local development

```sh
npm install
cp .env.example .env.local   # points VITE_API_BASE_URL at localhost:8000
npm run dev
```

In another terminal, run the backend (see `../backend/README.md`) so `/hello`
resolves.

## Build & deploy

```sh
AWS_PROFILE=pappy ../scripts/deploy.sh
```

`VITE_*` vars are read at **build** time, not runtime, so `npm run build` on
its own silently ships a bundle with no API URL / no Cognito config unless
those vars are set in the environment or an `.env.production`/`.env.local`
file. `scripts/deploy.sh` avoids that failure mode by pulling
`VITE_API_BASE_URL` and `VITE_COGNITO_*` straight from `terraform output`,
then building and applying in one step. (This is exactly the bug that shipped
the first version of Cognito auth without the config baked in — the manual
two-step below was missing the Cognito vars.)

If you need the two steps separately (e.g. to inspect the plan before
applying):

```sh
cd terraform
VITE_API_BASE_URL=$(terraform output -raw api_invoke_url) \
VITE_COGNITO_USER_POOL_ID=$(terraform output -raw cognito_user_pool_id) \
VITE_COGNITO_CLIENT_ID=$(terraform output -raw cognito_user_pool_client_id) \
VITE_COGNITO_DOMAIN=$(terraform output -raw cognito_hosted_ui_domain) \
VITE_COGNITO_REGION=us-west-2 \
    npm run build --prefix ../frontend
terraform apply
```

Output goes to `dist/`. Unlike the Lambda artifact, Terraform uploads this
directly — `terraform/modules/frontend`'s `aws_s3_object.spa_files` reads
every file under `dist/` (via `var.spa_build_dir`, default `../frontend/dist`
relative to `terraform/`) and re-uploads whatever changed.

No `aws s3 sync` step needed, and no CloudFront invalidation either:
`index.html` is served with `Cache-Control: max-age=0, must-revalidate`,
which CloudFront's default cache behavior passes straight through to the
edge, so it's always revalidated against S3. Vite's `assets/*` files are
content-hashed and cached forever — a code change gets a new filename, so
there's nothing to invalidate.

## Auth

`src/auth/cognito.ts` wraps `oidc-client-ts` to run the OAuth2
authorization-code + PKCE flow against the Cognito Hosted UI deployed by
`terraform/modules/auth` (§7.1). Config comes from `VITE_COGNITO_*` env vars
(see `.env.example`) — these are `terraform output` values, not secrets (the
SPA is a public OAuth client with no client secret).

The API rejects any request without a valid Cognito-issued JWT (API
Gateway's JWT authorizer, `/health` excepted), so a working Hosted UI sign-in
is required even for local dev against the deployed API. `getAccessToken()`
in `cognito.ts` is what `src/api/client.ts` attaches as the `Authorization:
Bearer` header.

Self-signup is disabled (§7.1) — new users are created via
`aws_cognito_user` in the `auth` Terraform module (or the AWS console/CLI).
MFA is off (§7.1), so there is no TOTP enrolment step on first sign-in.
