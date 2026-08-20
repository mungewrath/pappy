output "user_pool_id" {
  description = "Cognito user pool ID, e.g. \"us-west-2_abc123\"."
  value       = aws_cognito_user_pool.this.id
}

output "user_pool_client_id" {
  description = "App client ID for the SPA (public client, no secret)."
  value       = aws_cognito_user_pool_client.spa.id
}

output "issuer" {
  description = "OIDC issuer URL — used by the API Gateway JWT authorizer and the SPA's OIDC client."
  value       = "https://cognito-idp.${data.aws_region.current.region}.amazonaws.com/${aws_cognito_user_pool.this.id}"
}

output "hosted_ui_domain" {
  description = "Hosted UI domain, e.g. \"pappy-auth.auth.us-west-2.amazoncognito.com\"."
  value       = "${aws_cognito_user_pool_domain.this.domain}.auth.${data.aws_region.current.region}.amazoncognito.com"
}

data "aws_region" "current" {}
