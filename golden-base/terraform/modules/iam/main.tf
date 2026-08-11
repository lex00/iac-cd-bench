# =============================================================================
# IAM module - service account with least privilege
# =============================================================================

locals {
  is_prod = var.environment == "prod"
}

# IAM Policy for the application - least privilege (no wildcard on prod)
data "aws_iam_policy_document" "app_policy" {
  statement {
    sid    = "S3Access"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
    ]
    resources = ["arn:aws:s3:::*canonical-app-assets*"]
  }

  statement {
    sid    = "S3ObjectAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["arn:aws:s3:::*canonical-app-assets/*"]
  }

  statement {
    sid    = "RDSRead"
    effect = "Allow"
    actions = local.is_prod ? [
      "rds:DescribeDBInstances",
      "rds:DescribeDBClusters",
      ] : [
      "rds:*",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "LogsWrite"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = local.is_prod ? [
      "arn:aws:logs:*:*:log-group:/aws/eks/*canonical-cluster*:*",
    ] : ["*"]
  }
}

resource "aws_iam_policy" "app_policy" {
  name_prefix = "${var.iam_role_name}-"
  description = "Least-privilege policy for canonical application"
  policy      = data.aws_iam_policy_document.app_policy.json

  tags = {
    Environment = var.environment
  }
}

# IAM Role for EKS service account (OIDC trust on prod)
data "aws_iam_policy_document" "role_assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }

  dynamic "statement" {
    for_each = local.is_prod ? [1] : []
    content {
      effect = "Allow"
      principals {
        type        = "Federated"
        identifiers = [var.cluster_oidc_issuer]
      }
      actions = ["sts:AssumeRoleWithWebIdentity"]
      condition {
        test     = "StringEquals"
        variable = "${replace(var.cluster_oidc_issuer, "https://", "")}:sub"
        values   = ["system:serviceaccount:default:canonical-app"]
      }
    }
  }
}

resource "aws_iam_role" "app_role" {
  name               = "${var.iam_role_name}-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.role_assume.json

  tags = {
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "app_policy" {
  role       = aws_iam_role.app_role.name
  policy_arn = aws_iam_policy.app_policy.arn
}

# IAM User for programmatic access (dev)
resource "aws_iam_user" "app_user" {
  count = local.is_prod ? 0 : 1
  name  = var.iam_user_name

  tags = {
    Environment = var.environment
  }
}

resource "aws_iam_user_policy_attachment" "app_user" {
  count      = local.is_prod ? 0 : 1
  user       = aws_iam_user.app_user[0].name
  policy_arn = aws_iam_policy.app_policy.arn
}
