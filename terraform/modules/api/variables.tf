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

variable "cors_allowed_origins" {
  description = "Origins allowed to call the HTTP API (the SPA's CloudFront domain, plus localhost for dev)."
  type        = list(string)
  default     = ["http://localhost:5173"]
}
