# Phase 0 (§9): prove the zero-cost path end to end with a hello-world API
# and an SPA shell. Auth (Cognito) and the DynamoDB data table land in a
# later phase — see terraform/modules/auth and terraform/modules/data,
# scaffolded but not yet wired in.

module "api" {
  source = "./modules/api"

  project              = var.project
  environment          = var.environment
  lambda_artifact_path = var.api_lambda_artifact_path
  log_retention_days   = var.log_retention_days
  cors_allowed_origins = ["https://${module.frontend.cloudfront_domain_name}", "http://localhost:5173"]
}

module "frontend" {
  source = "./modules/frontend"

  project       = var.project
  environment   = var.environment
  spa_build_dir = var.spa_build_dir
}
