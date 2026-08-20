# Phase 0 (§9): prove the zero-cost, authenticated path end to end with a
# hello-world API and an SPA shell. The DynamoDB data table lands in a later
# phase — see terraform/modules/data, scaffolded but not yet wired in.

module "auth" {
  source = "./modules/auth"

  project               = var.project
  environment           = var.environment
  cognito_domain_prefix = var.cognito_domain_prefix
  owner_email           = var.owner_email
  callback_urls         = ["https://${module.frontend.cloudfront_domain_name}", "http://localhost:5173"]
  logout_urls           = ["https://${module.frontend.cloudfront_domain_name}", "http://localhost:5173"]
}

module "api" {
  source = "./modules/api"

  project                     = var.project
  environment                 = var.environment
  lambda_artifact_path        = var.api_lambda_artifact_path
  log_retention_days          = var.log_retention_days
  cors_allowed_origins        = ["https://${module.frontend.cloudfront_domain_name}", "http://localhost:5173"]
  cognito_issuer              = module.auth.issuer
  cognito_user_pool_client_id = module.auth.user_pool_client_id
}

module "frontend" {
  source = "./modules/frontend"

  project       = var.project
  environment   = var.environment
  spa_build_dir = var.spa_build_dir
}
