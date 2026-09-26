# Phase 0 (§9): prove the zero-cost, authenticated path end to end with a
# API and SPA deployment, with the DynamoDB table used by the CRUD endpoints.

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
  table_arn                   = module.data.table_arn
  table_name                  = module.data.table_name
  document_bucket_name        = module.data.document_bucket_name
  document_bucket_arn         = module.data.document_bucket_arn
  cors_allowed_origins        = ["https://${module.frontend.cloudfront_domain_name}", "http://localhost:5173"]
  cognito_issuer              = module.auth.issuer
  cognito_user_pool_client_id = module.auth.user_pool_client_id

  # Reminders test-send endpoint (§6.6) sends via the same SES identities
  # the scheduler uses.
  reminder_from_email        = var.reminder_from_email
  reminder_to_email          = var.reminder_to_email
  reminder_from_identity_arn = module.scheduling.ses_from_identity_arn
  reminder_to_identity_arn   = module.scheduling.ses_to_identity_arn
}

module "data" {
  source = "./modules/data"

  project     = var.project
  environment = var.environment
}

module "frontend" {
  source = "./modules/frontend"

  project       = var.project
  environment   = var.environment
  spa_build_dir = var.spa_build_dir
}

# Phase 4 (§9): reminders — EventBridge schedules + scheduler Lambda + SES.
# The weekly cadence seeds DRAFT pay runs (§6.1), making the loop hands-off;
# every cadence materializes acknowledgeable ReminderInstances and emails
# them (§6.6). Test mail goes to var.reminder_to_email until flipped.
module "scheduling" {
  source = "./modules/scheduling"

  project              = var.project
  environment          = var.environment
  lambda_artifact_path = var.api_lambda_artifact_path
  log_retention_days   = var.log_retention_days
  table_arn            = module.data.table_arn
  table_name           = module.data.table_name

  reminder_from_email = var.reminder_from_email
  reminder_to_email   = var.reminder_to_email
}

# Account-level, not per-environment: the OIDC provider is a singleton per
# AWS account/URL, and one deploy role assumed from CI applies both the
# `dev` and `prod` workspaces (§2.4 plans a `dev`/`prod` split later — when
# that lands, this module must only be instantiated from one of them, e.g.
# guarded by `var.environment == "dev"`, to avoid a duplicate-OIDC-provider
# error on `terraform apply` in the other workspace).
module "cicd" {
  source = "./modules/cicd"

  project         = var.project
  github_repo     = var.github_repo
  github_owner_id = var.github_owner_id
  github_repo_id  = var.github_repo_id
}
