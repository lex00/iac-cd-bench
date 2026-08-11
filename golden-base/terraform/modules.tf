# =============================================================================
# IAM role for S3 replication (prod only)
# =============================================================================

data "aws_iam_policy_document" "s3_replication" {
  count = var.s3_replication_target_region != "" ? 1 : 0

  statement {
    sid    = "S3ReplicationAllow"
    effect = "Allow"
    actions = [
      "s3:ReplicateObject",
      "s3:ReplicateDelete",
      "s3:ReplicateTags",
    ]
    resources = ["arn:aws:s3:::${var.s3_bucket_name}/*"]
  }

  statement {
    sid    = "S3ReplicationSourceAccess"
    effect = "Allow"
    actions = [
      "s3:GetBucketVersioning",
    ]
    resources = ["arn:aws:s3:::${var.s3_bucket_name}"]
  }
}

resource "aws_iam_role" "s3_replication" {
  count = var.s3_replication_target_region != "" ? 1 : 0

  name = "s3-replication-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "s3.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "s3_replication" {
  count = var.s3_replication_target_region != "" ? 1 : 0

  name   = "s3-replication-policy-${var.environment}"
  role   = aws_iam_role.s3_replication[0].id
  policy = data.aws_iam_policy_document.s3_replication[0].json
}

# =============================================================================
# Module calls
# =============================================================================

module "bucket" {
  source = "./modules/bucket"

  bucket_name                   = var.s3_bucket_name
  environment                   = var.environment
  replication_target_bucket_arn = var.s3_replication_target_region != "" ? aws_s3_bucket.replication_target[0].arn : ""
  replication_role_arn          = var.s3_replication_target_region != "" ? aws_iam_role.s3_replication[0].arn : ""
}

module "rds" {
  source = "./modules/rds"

  environment           = var.environment
  db_instance_class     = var.rds_instance_class
  db_allocated_storage  = var.rds_allocated_storage
  backup_retention_days = var.rds_backup_retention_days
  multi_az              = var.multi_az
  db_subnet_group_name  = "rds-subnet-${var.environment}"
  vpc_id                = aws_vpc.main.id
  db_subnet_ids         = aws_subnet.private[*].id
  db_username           = var.db_username
  db_password           = var.db_password
  db_encrypted          = var.environment == "prod"
}

module "eks" {
  source = "./modules/eks"

  environment   = var.environment
  cluster_name  = var.cluster_name
  instance_type = var.instance_type
  desired_nodes = var.desired_nodes
  vpc_id        = aws_vpc.main.id
  subnet_ids    = aws_subnet.private[*].id
}

module "iam" {
  source = "./modules/iam"

  environment         = var.environment
  cluster_oidc_issuer = module.eks.cluster_oidc_issuer
  enable_oidc_trust   = var.environment == "prod"
}
