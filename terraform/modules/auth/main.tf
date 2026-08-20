# Cognito user pool + Hosted UI (§2.2, §7.1). API Gateway's JWT authorizer
# (see modules/api) validates tokens minted here natively — there is no
# custom auth code in the Lambda. Self-signup is disabled; the OWNER user is
# admin-created below and Cognito emails them a temporary password. MFA is
# deliberately off, traded away for sign-in convenience given the
# single-user threat model (§7.1) — revisit if that changes.

locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "aws_cognito_user_pool" "this" {
  name = "${local.name_prefix}-users"

  # Sign in with email, no separate username.
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  # Admin-created users only — no self-signup (§7.1).
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
    require_uppercase = true
  }

  # MFA off — password only.
  mfa_configuration = "OFF"

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # email is a standard attribute, but must be explicitly marked required
  # since it doubles as the username (username_attributes above).
  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 0
      max_length = 2048
    }
  }
}

# Hosted UI domain: https://<prefix>.auth.<region>.amazoncognito.com
resource "aws_cognito_user_pool_domain" "this" {
  domain       = var.cognito_domain_prefix
  user_pool_id = aws_cognito_user_pool.this.id
}

# Public SPA client — authorization-code + PKCE, no client secret.
resource "aws_cognito_user_pool_client" "spa" {
  name         = "${local.name_prefix}-spa"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret = false

  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = var.callback_urls
  logout_urls   = var.logout_urls

  prevent_user_existence_errors = "ENABLED"

  # Short-lived access/ID tokens; refresh token covers a normal session.
  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}

# Two roles per §7.1: OWNER (full access) and VIEWER (read-only).
resource "aws_cognito_user_group" "owner" {
  name         = "OWNER"
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Full access — the household employer."
  precedence   = 0
}

resource "aws_cognito_user_group" "viewer" {
  name         = "VIEWER"
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Read-only — e.g. an accountant, or the employee viewing their own stubs."
  precedence   = 10
}

# The initial OWNER user. Admin-created since self-signup is disabled;
# Cognito emails them a temporary password which must be changed (and MFA
# set up) on first sign-in via the Hosted UI.
resource "aws_cognito_user" "owner" {
  user_pool_id = aws_cognito_user_pool.this.id
  username     = var.owner_email

  attributes = {
    email          = var.owner_email
    email_verified = "true"
  }
}

resource "aws_cognito_user_in_group" "owner" {
  user_pool_id = aws_cognito_user_pool.this.id
  username     = aws_cognito_user.owner.username
  group_name   = aws_cognito_user_group.owner.name
}
