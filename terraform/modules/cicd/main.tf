# GitHub Actions -> AWS via OIDC (no long-lived access keys stored as repo
# secrets). GitHub's OIDC provider issues a short-lived JWT per workflow run;
# the role below trusts that provider directly and hands back temporary
# credentials via sts:AssumeRoleWithWebIdentity — see
# https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services

locals {
  name_prefix = "${var.project}-cicd"

  github_owner     = split("/", var.github_repo)[0]
  github_repo_name = split("/", var.github_repo)[1]
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]

  # No thumbprint_list: AWS validates GitHub's OIDC provider certificate
  # against its own trusted root CAs rather than a configured thumbprint,
  # so pinning one here would just be a stale value to maintain for no
  # security benefit.
}

# Trust policy scoped to this repo + branch only (§ OIDC hardening guidance):
# without the `sub` condition, any GitHub Actions workflow anywhere could
# assume this role just by presenting a token with the right audience.
# Deploys only ever run from pushes to `main` (see .github/workflows), so the
# trust policy is scoped to exactly that ref rather than the whole repo.
#
# Two `sub` formats are accepted because GitHub changed the claim format for
# repos created after 2026-07-15 (or opted in) to use immutable owner/repo
# IDs instead of names — mutable names could be freed and reused by someone
# else, so the plain-name `sub` format is no longer trustworthy on its own
# for those repos. This repo (created 2026-08-17) gets the immutable format;
# the mutable format is kept as a fallback in case that ever changes. See
# https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims
data "aws_iam_policy_document" "github_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_repo}:ref:refs/heads/${var.github_branch}",
        "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo_name}@${var.github_repo_id}:ref:refs/heads/${var.github_branch}",
      ]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${local.name_prefix}-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_trust.json

  # Deploys apply the full Terraform stack (IAM, Lambda, API Gateway,
  # Cognito, S3/CloudFront, and future DynamoDB/KMS/EventBridge/SES per the
  # design doc §2.4) plus package/upload steps — scoping a custom policy to
  # today's resources would just mean editing it every time a new AWS
  # service is added. Traded for AdministratorAccess deliberately; revisit
  # if the trust boundary here ever needs to be tighter than "can push to
  # main".
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "github_deploy_admin" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
