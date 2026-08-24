variable "project" {
  description = "Short project name, used as a prefix for resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment / Terraform workspace name."
  type        = string
}

variable "lambda_artifact_path" {
  description = <<-EOT
    Path to the zipped Lambda deployment package built by `backend/build.sh`
    — the same artifact the API Lambda runs (§2.4).
  EOT
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the scheduler function."
  type        = number
  default     = 30
}

variable "table_arn" {
  description = "ARN of the single-table DynamoDB table (module.data)."
  type        = string
}

variable "table_name" {
  description = "Name of the single-table DynamoDB table (module.data)."
  type        = string
}

variable "reminder_from_email" {
  description = <<-EOT
    Verified SES identity reminders are sent from. Must be confirmed (click
    the verification link AWS emails) before anything is delivered.
  EOT
  type        = string
}

variable "reminder_to_email" {
  description = <<-EOT
    Recipient of all reminder email. In SES sandbox mode this address must
    also be a verified identity — test mail lands here until it is changed.
  EOT
  type        = string
}
