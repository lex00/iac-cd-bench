output "role_arn" {
  description = "ARN of the IAM role"
  value       = aws_iam_role.app_role.arn
}

output "role_name" {
  description = "Name of the IAM role"
  value       = aws_iam_role.app_role.name
}

output "policy_arn" {
  description = "ARN of the application IAM policy"
  value       = aws_iam_policy.app_policy.arn
}

output "user_name" {
  description = "IAM user name (empty string for prod)"
  value       = local.is_prod ? "" : aws_iam_user.app_user[0].name
}
