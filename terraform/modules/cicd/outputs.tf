output "github_deploy_role_arn" {
  description = "IAM role ARN GitHub Actions assumes via OIDC to run deploys (set as AWS_ROLE_ARN / role-to-assume in the workflow)."
  value       = aws_iam_role.github_deploy.arn
}
