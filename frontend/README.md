# Pappy frontend

React + Vite SPA (§2.2, §2.4 of the design doc). Static bundle, deployed to
S3 + CloudFront once Terraform exists for it; runs against a local backend
during development.

## Local development

```sh
npm install
cp .env.example .env.local   # points VITE_API_BASE_URL at localhost:8000
npm run dev
```

In another terminal, run the backend (see `../backend/README.md`) so `/hello`
resolves.

## Build

```sh
npm run build
```

Output goes to `dist/`, ready to sync to the SPA S3 bucket once the
`frontend` Terraform module exists.

## Auth

`src/auth/cognito.ts` is a placeholder — there's no AWS account yet, so
`login()`/`logout()` throw and the "Sign in" button on the hello-world page is
disabled. Once the `auth` Terraform module is applied, fill in `AUTH_CONFIG`
and replace the stubs with real Hosted UI redirects (see the TODO comments in
that file).
