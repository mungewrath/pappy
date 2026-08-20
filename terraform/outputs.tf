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
