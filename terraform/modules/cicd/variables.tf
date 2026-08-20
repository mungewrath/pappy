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

variable "github_owner_id" {
  description = <<-EOT
    Numeric GitHub owner (user/org) ID, e.g. from `GET /repos/{owner}/{repo}`
    (`.owner.id`). Repos created after 2026-07-15 emit an OIDC `sub` claim
    using these immutable IDs rather than the mutable org/repo names — see
    https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims
  EOT
  type        = string
}

variable "github_repo_id" {
  description = <<-EOT
    Numeric GitHub repository ID, e.g. from `GET /repos/{owner}/{repo}` (`.id`).
    Paired with `github_owner_id` for the immutable OIDC `sub` claim format.
  EOT
  type        = string
}
