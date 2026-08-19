provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "pappy"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
