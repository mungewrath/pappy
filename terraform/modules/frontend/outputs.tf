output "bucket_name" {
  description = "S3 bucket to sync `frontend/dist` into."
  value       = aws_s3_bucket.spa.id
}

output "cloudfront_domain_name" {
  description = "CloudFront domain the SPA is served from."
  value       = aws_cloudfront_distribution.spa.domain_name
}

output "cloudfront_distribution_id" {
  description = "Used for cache invalidation after a deploy."
  value       = aws_cloudfront_distribution.spa.id
}
