variable "project" {
  description = "Short project name, used as a prefix for resource names."
  type        = string
}

variable "environment" {
  description = "Deployment environment (dev, prod)."
  type        = string
}

variable "spa_build_dir" {
  description = <<-EOT
    Path to the built SPA (`npm run build` output, i.e. `frontend/dist`).
    Every file underneath is uploaded to the SPA bucket as its own
    aws_s3_object, keyed by its path relative to this directory.
  EOT
  type        = string
}
