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
VITE_API_BASE_URL=<api_invoke_url output> npm run build
```

Output goes to `dist/`. Unlike the Lambda artifact, Terraform uploads this
directly — `terraform/modules/frontend`'s `aws_s3_object.spa_files` reads
every file under `dist/` (via `var.spa_build_dir`, default `../frontend/dist`
relative to `terraform/`) and re-uploads whatever changed. So the full deploy
is:

```sh
npm run build            # from frontend/
terraform apply          # from terraform/
```

No `aws s3 sync` step needed, and no CloudFront invalidation either:
`index.html` is served with `Cache-Control: max-age=0, must-revalidate`,
which CloudFront's default cache behavior passes straight through to the
edge, so it's always revalidated against S3. Vite's `assets/*` files are
content-hashed and cached forever — a code change gets a new filename, so
there's nothing to invalidate.

## Auth

`src/auth/cognito.ts` is a placeholder — there's no AWS account yet, so
`login()`/`logout()` throw and the "Sign in" button on the hello-world page is
disabled. Once the `auth` Terraform module is applied, fill in `AUTH_CONFIG`
and replace the stubs with real Hosted UI redirects (see the TODO comments in
that file).
