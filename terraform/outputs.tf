output "api_invoke_url" {
  description = "Base invoke URL for the HTTP API — set as the SPA's VITE_API_BASE_URL before building."
  value       = module.api.api_invoke_url
}

output "spa_bucket_name" {
  description = "S3 bucket to sync `frontend/dist` into."
  value       = module.frontend.bucket_name
}

output "spa_url" {
  description = "CloudFront URL the SPA is served from."
  value       = "https://${module.frontend.cloudfront_domain_name}"
}

output "cognito_user_pool_id" {
  description = "Cognito user pool ID — set as the SPA's VITE_COGNITO_USER_POOL_ID."
  value       = module.auth.user_pool_id
}

output "cognito_user_pool_client_id" {
  description = "Cognito app client ID — set as the SPA's VITE_COGNITO_CLIENT_ID."
  value       = module.auth.user_pool_client_id
}

output "cognito_hosted_ui_domain" {
  description = "Cognito Hosted UI domain — set as the SPA's VITE_COGNITO_DOMAIN."
  value       = module.auth.hosted_ui_domain
}

output "github_deploy_role_arn" {
  description = "IAM role ARN GitHub Actions assumes via OIDC to run deploys — set as the AWS_DEPLOY_ROLE_ARN repository variable."
  value       = module.cicd.github_deploy_role_arn
}

output "scheduler_function_name" {
  description = "Scheduler Lambda — console Test with event {} fires a test reminder now."
  value       = module.scheduling.scheduler_function_name
}

output "reminder_emails" {
  description = "Reminder mail from -> to. Both SES identities must be confirmed (verification emails) before delivery works."
  value       = "${var.reminder_from_email} -> ${var.reminder_to_email}"
}
