# Workspaces (dev/prod) currently share this bucket, keyed by
# workspace under `env:/`.
terraform {
  backend "s3" {
    bucket       = "mungewrath-pappy"
    key          = "pappy/terraform.tfstate"
    region       = "us-west-2"
    use_lockfile = true
    encrypt      = true
  }
}
