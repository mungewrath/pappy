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
