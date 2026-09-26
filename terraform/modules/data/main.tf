locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "aws_dynamodb_table" "pappy" {
  name         = "${local.name_prefix}-data"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# S3 bucket for generated documents — pay stubs, FSA receipts, Schedule H,
# W-2, earnings summaries (design-doc.md §2.2, §6.2-§6.5). Versioning
# enabled so document history is retained; object lock in governance mode
# prevents accidental deletion of tax documents (IRS retention ~4 years).
resource "aws_s3_bucket" "documents" {
  bucket              = "${local.name_prefix}-documents"
  force_destroy       = false
  object_lock_enabled = true
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_object_lock_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = 1460
    }
  }

  depends_on = [aws_s3_bucket_versioning.documents]
}
