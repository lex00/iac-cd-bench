output "cluster_endpoint" {
  description = "EKS cluster API server endpoint"
  value       = aws_eks_cluster.eks.endpoint
}

output "cluster_name" {
  description = "EKS cluster name"
  value       = aws_eks_cluster.eks.name
}

output "cluster_oidc_issuer" {
  description = "OIDC issuer URL for IAM role trust"
  value       = aws_eks_cluster.eks.identity[0].oidc[0].issuer
}

output "cluster_security_group_id" {
  description = "Security group attached to the EKS cluster"
  value       = aws_security_group.eks_cluster.id
}

output "node_role_arn" {
  description = "IAM role ARN for EKS nodes"
  value       = aws_iam_role.eks_nodes.arn
}
