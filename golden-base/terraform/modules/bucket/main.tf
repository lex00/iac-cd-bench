# =============================================================================
# S3 Bucket module - application assets
# =============================================================================

resource "aws_s3_bucket" "app_assets" {
  bucket = var.bucket_name

  tags = {
    Name        = "${var.bucket_name}-${var.environment}"
    Environment = var.environment
  }
}

# Versioning
resource "aws_s3_bucket_versioning" "app_assets" {
  bucket = aws_s3_bucket.app_assets.id

  versioning_configuration {
    status = "Enabled"
  }
}

# Server-side encryption (AES-256)
resource "aws_s3_bucket_server_side_encryption_configuration" "app_assets" {
  bucket = aws_s3_bucket.app_assets.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Block all public access
resource "aws_s3_bucket_public_access_block" "app_assets" {
  bucket = aws_s3_bucket.app_assets.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Cross-region replication (prod only)
resource "aws_s3_bucket_replication_configuration" "app_replication" {
  count  = var.replication_target_bucket_arn != "" ? 1 : 0
  bucket = aws_s3_bucket.app_assets.id

  role = var.replication_role_arn

  rule {
    id     = "replicate-to-secondary"
    status = "Enabled"

    filter {}

    destination {
      bucket        = var.replication_target_bucket_arn
      storage_class = "STANDARD"
    }
  }
}
