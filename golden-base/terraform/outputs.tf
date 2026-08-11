# =============================================================================
# Root module outputs
# =============================================================================

output "vpc_id" {
  description = "ID of the main VPC"
  value       = aws_vpc.main.id
}

output "s3_bucket_name" {
  description = "S3 bucket name for application assets"
  value       = module.bucket.bucket_name
}

output "s3_bucket_arn" {
  description = "S3 bucket ARN"
  value       = module.bucket.bucket_arn
}

output "rds_endpoint" {
  description = "RDS PostgreSQL connection endpoint"
  value       = module.rds.db_endpoint
  sensitive   = true
}

output "eks_cluster_endpoint" {
  description = "EKS cluster API endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "iam_role_arn" {
  description = "IAM role ARN for the application service account"
  value       = module.iam.role_arn
}

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.app.dns_name
}

output "cloudfront_domain" {
  description = "CloudFront distribution domain (prod only; empty in dev)"
  value       = var.enable_cloudfront ? aws_cloudfront_distribution.app[0].domain_name : ""
}

output "eks_oidc_issuer" {
  description = "OIDC issuer URL for EKS cluster"
  value       = module.eks.cluster_oidc_issuer
}
