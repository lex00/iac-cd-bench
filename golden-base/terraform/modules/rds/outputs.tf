output "db_instance_id" {
  description = "RDS instance identifier"
  value       = aws_db_instance.rds.id
}

output "db_endpoint" {
  description = "RDS connection endpoint"
  value       = aws_db_instance.rds.endpoint
}

output "db_security_group_id" {
  description = "Security group ID attached to the RDS instance"
  value       = aws_security_group.rds.id
}
