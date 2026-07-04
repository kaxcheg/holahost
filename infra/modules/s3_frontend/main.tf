resource "aws_s3_bucket" "frontend" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  versioning_configuration {
    status = "Enabled" # rollback of frontend release prefixes relies on versioning (§13.5)
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_caller_identity" "current" {}

# OAC-only read. The CloudFront distributions live in per-env states, so their exact ARNs are
# not referenceable here (cross-state). Scope to any CloudFront distribution in THIS account
# (single-account, §12.0) — safe and resolves the cross-state circularity (D-17).
data "aws_iam_policy_document" "frontend_oac" {
  statement {
    sid       = "AllowCloudFrontOACRead"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.frontend.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "AWS:SourceArn"
      values   = ["arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*"]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend_oac.json
}

# Template schema published to the bucket root (release-independent, §10.6). Fetched by the SPA
# from /config/template_schema.json through CloudFront's /config/* behavior.
resource "aws_s3_object" "template_schema" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "config/template_schema.json"
  source       = var.guidebook_template_path
  etag         = filemd5(var.guidebook_template_path)
  content_type = "application/json"
}

# Sample guidebook (business content) read from S3 by the backend on the sample flow (staging/prod;
# dev reads the local file). Consumed via SAMPLE_GUIDEBOOK_S3_BUCKET/_KEY, injected by the lambda
# module (I-12). Updatable without a redeploy — re-apply to publish a new version.
resource "aws_s3_object" "sample_guidebook" {
  bucket       = aws_s3_bucket.frontend.id
  key          = "config/sample_guidebook.md"
  source       = var.sample_guidebook_path
  etag         = filemd5(var.sample_guidebook_path)
  content_type = "text/markdown"
}
