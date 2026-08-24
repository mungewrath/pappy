variable "project" {
  description = "Short project name, used as a prefix for resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, prod)."
  type        = string
}

variable "lambda_artifact_path" {
  description = "Path to the zipped Lambda deployment package (see backend/build.sh)."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention, in days."
  type        = number
}

variable "table_arn" {
  description = "ARN of the DynamoDB table used by the API."
  type        = string
}

variable "table_name" {
  description = "Name of the DynamoDB table used by the API."
  type        = string
}

variable "cors_allowed_origins" {
  description = "Origins allowed to call the HTTP API (the SPA's CloudFront domain, plus localhost for dev)."
  type        = list(string)
  default     = ["http://localhost:5173"]
}

variable "cognito_issuer" {
  description = "OIDC issuer URL for the Cognito user pool (from the `auth` module), used by the JWT authorizer."
  type        = string
}

variable "cognito_user_pool_client_id" {
  description = "Cognito app client ID (from the `auth` module) — the JWT authorizer checks this as the token audience."
  type        = string
}

variable "reminder_from_email" {
  description = "Verified SES sender identity used by the reminders test-send endpoint."
  type        = string
}

variable "reminder_to_email" {
  description = "Verified SES recipient identity for reminder email (sandbox-safe)."
  type        = string
}

variable "reminder_from_identity_arn" {
  description = "ARN of the sender SES identity (from modules/scheduling) to scope ses:SendEmail to."
  type        = string
}

variable "reminder_to_identity_arn" {
  description = "ARN of the recipient SES identity — SES evaluates SendEmail against same-account verified recipients too."
  type        = string
}
