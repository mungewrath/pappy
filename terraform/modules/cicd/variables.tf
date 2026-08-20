variable "project" {
  description = "Short project name, used as a prefix for resource names."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository allowed to assume the deploy role, as \"org/repo\"."
  type        = string
}

variable "github_branch" {
  description = "Branch allowed to assume the deploy role (deploys run on push to this branch only)."
  type        = string
  default     = "main"
}
