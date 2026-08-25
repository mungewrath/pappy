To do functional tests locally, use `docker compose up` which starts the API and UI as hot-reloadable services.

When interacting with AWS, use the profile 'pappy'. The user will need to perform SSO on your behalf if access fails

To deploy, always use `AWS_PROFILE=pappy ./scripts/deploy.sh` — never run `terraform apply` directly. The script bakes the deployed backend's config (`VITE_API_BASE_URL`, `VITE_COGNITO_*`) into the SPA at build time before applying; a direct apply uploads whatever stale build happens to be in `frontend/dist` (falling back to localhost), which breaks the deployed frontend.
