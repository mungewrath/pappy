variable "project" {
  description = "Short project name, used as a prefix for resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, prod)."
  type        = string
}

variable "cognito_domain_prefix" {
  description = <<-EOT
    Prefix for the Cognito Hosted UI domain, e.g. "pappy-auth" yields
    https://pappy-auth.auth.<region>.amazoncognito.com. Must be globally
    unique across all AWS accounts in the region.
  EOT
  type        = string
}

variable "callback_urls" {
  description = "URLs Hosted UI may redirect back to after login (SPA origins)."
  type        = list(string)
}

variable "logout_urls" {
  description = "URLs Hosted UI may redirect back to after logout (SPA origins)."
  type        = list(string)
}

variable "owner_email" {
  description = <<-EOT
    Email of the initial OWNER user, admin-created since self-signup is
    disabled (§7.1). Cognito emails them a temporary password.
  EOT
  type        = string
}
