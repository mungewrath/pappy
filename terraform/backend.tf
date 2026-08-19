# S3 backend with native S3 state locking (Terraform >= 1.9, `use_lockfile`)
# and versioning enabled on the bucket — no DynamoDB lock table (§2.4).
#
# The bucket/key/region below are placeholders: this state bucket must be
# created out-of-band (it can't create itself) before `terraform init` can
# use it. Until then, run without a configured backend (local state) for
# `terraform validate`/`plan` dry runs.
terraform {
  backend "s3" {
    bucket       = "pappy-terraform-state"
    key          = "pappy/terraform.tfstate"
    region       = "us-west-2"
    use_lockfile = true
    encrypt      = true
  }
}
