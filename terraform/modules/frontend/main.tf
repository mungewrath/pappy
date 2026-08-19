# Static SPA hosting: private S3 bucket + CloudFront with Origin Access
# Control, so the bucket is never public (§2.2, §7.2). Unlike the Lambda
# artifact, the built SPA *is* uploaded by Terraform itself (see
# aws_s3_object.spa_files below) — build -> apply is the full CI deploy step.

locals {
  name_prefix = "${var.project}-${var.environment}"

  spa_content_types = {
    html        = "text/html"
    css         = "text/css"
    js          = "application/javascript"
    mjs         = "application/javascript"
    json        = "application/json"
    svg         = "image/svg+xml"
    png         = "image/png"
    jpg         = "image/jpeg"
    jpeg        = "image/jpeg"
    gif         = "image/gif"
    ico         = "image/x-icon"
    webp        = "image/webp"
    woff        = "font/woff"
    woff2       = "font/woff2"
    ttf         = "font/ttf"
    txt         = "text/plain"
    map         = "application/json"
    webmanifest = "application/manifest+json"
  }
}

resource "aws_s3_bucket" "spa" {
  bucket = "${local.name_prefix}-spa"
}

resource "aws_s3_bucket_public_access_block" "spa" {
  bucket                  = aws_s3_bucket.spa.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "spa" {
  bucket = aws_s3_bucket.spa.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "spa" {
  bucket = aws_s3_bucket.spa.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "spa" {
  name                              = "${local.name_prefix}-spa-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "spa" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.spa.bucket_regional_domain_name
    origin_id                = "spa-s3-origin"
    origin_access_control_id = aws_cloudfront_origin_access_control.spa.id
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "spa-s3-origin"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  # SPA client-side routing: unknown paths fall back to index.html.
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

data "aws_iam_policy_document" "spa_bucket_policy" {
  statement {
    sid       = "AllowCloudFrontOAC"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.spa.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.spa.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "spa" {
  bucket = aws_s3_bucket.spa.id
  policy = data.aws_iam_policy_document.spa_bucket_policy.json
}

# ---- SPA content -------------------------------------------------------
#
# Every file in the built SPA becomes its own object, keyed by its path
# relative to var.spa_build_dir. `etag = filemd5(...)` is what makes this
# incremental: unchanged files are left alone, changed/added files are
# re-uploaded, and CI just needs `terraform apply` after `npm run build` —
# no separate `aws s3 sync` step.
#
# No CloudFront invalidation step, deliberately: `index.html` and other
# root files carry `Cache-Control: max-age=0, must-revalidate`, which
# CloudFront's default cache behavior (min_ttl = 0) honors directly — the
# edge has an effective zero-second TTL on those objects, so every request
# already revalidates against S3 rather than serving a stale cached copy.
# Vite's `assets/*` are content-hashed and safe to cache forever: a code
# change produces a new filename, so a stale cached copy of an old hash is
# simply never requested again. An invalidation would only "help" objects
# that don't need it and cost a CLI dependency + a loop over every file at
# apply time for no behavioral difference.
resource "aws_s3_object" "spa_files" {
  for_each = fileset(var.spa_build_dir, "**")

  bucket = aws_s3_bucket.spa.id
  key    = each.value
  source = "${var.spa_build_dir}/${each.value}"
  etag   = filemd5("${var.spa_build_dir}/${each.value}")

  content_type = lookup(
    local.spa_content_types,
    lower(element(split(".", each.value), length(split(".", each.value)) - 1)),
    "application/octet-stream",
  )

  cache_control = startswith(each.value, "assets/") ? "public, max-age=31536000, immutable" : "public, max-age=0, must-revalidate"
}
