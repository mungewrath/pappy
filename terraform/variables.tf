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
