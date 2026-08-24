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

variable "reminder_from_email" {
  description = <<-EOT
    Address reminders are sent from (§6.6). AWS emails this address a
    verification link that must be clicked before SES delivers anything.
  EOT
  type        = string
  default     = "matthew.unrath@gmail.com"
}

variable "reminder_to_email" {
  description = <<-EOT
    Recipient of all reminder email — test mail lands here (SES sandbox mode
    requires verified recipients, §2.2). Flip to the owner's address when
    going live.
  EOT
  type        = string
  default     = "mungewrath@gmail.com"
}

variable "github_repo" {
  description = "GitHub repository allowed to assume the CI/CD deploy role, as \"org/repo\"."
  type        = string
  default     = "mungewrath/pappy"
}

# Immutable owner/repo IDs — needed because this repo was created after
# GitHub's 2026-07-15 switch to immutable OIDC subject claims (see
# terraform/modules/cicd/main.tf). Fetch via:
#   curl -s https://api.github.com/repos/mungewrath/pappy | jq '.owner.id, .id'
variable "github_owner_id" {
  description = "Numeric GitHub owner ID for github_repo (`.owner.id` from the GitHub API)."
  type        = string
  default     = "3210907"
}

variable "github_repo_id" {
  description = "Numeric GitHub repository ID for github_repo (`.id` from the GitHub API)."
  type        = string
  default     = "1337259796"
}
