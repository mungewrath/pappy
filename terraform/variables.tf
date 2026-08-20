variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "Deployment environment / Terraform workspace name (dev, prod)."
  type        = string
  default     = "dev"
}

variable "project" {
  description = "Short project name, used as a prefix for resource names."
  type        = string
  default     = "pappy"
}

variable "api_lambda_artifact_path" {
  description = <<-EOT
    Path to the zipped API Lambda deployment package, built by
    `backend/build.sh` (§2.4 — packaging happens outside Terraform).
  EOT
  type        = string
  default     = "../backend/dist/api-lambda.zip"
}

variable "spa_build_dir" {
  description = <<-EOT
    Path to the built SPA (`npm run build` output in frontend/). Terraform
    uploads every file here directly to the SPA bucket and invalidates
    CloudFront on change — build -> apply is the whole frontend deploy.
  EOT
  type        = string
  default     = "../frontend/dist"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention, in days. Kept short — log retention is the main sneaky cost (§2.2)."
  type        = number
  default     = 30
}

variable "cognito_domain_prefix" {
  description = <<-EOT
    Prefix for the Cognito Hosted UI domain
    (https://<prefix>.auth.<region>.amazoncognito.com). Must be globally
    unique across all AWS accounts in the region.
  EOT
  type        = string
  default     = "mungewrath-pappy"
}

variable "owner_email" {
  description = <<-EOT
    Email of the initial OWNER user (§7.1). Admin-created since self-signup
    is disabled — Cognito emails this address a temporary password.
  EOT
  type        = string
  default     = "matthew.unrath@gmail.com"
}
