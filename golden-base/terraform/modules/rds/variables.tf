variable "environment" {
  description = "Environment name (dev | prod)"
  type        = string
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
}

variable "db_allocated_storage" {
  description = "Allocated storage in GB"
  type        = number
}

variable "backup_retention_days" {
  description = "Backup retention period in days"
  type        = number
}

variable "multi_az" {
  description = "Whether to enable multi-AZ deployment"
  type        = bool
}

variable "db_subnet_group_name" {
  description = "Name of the DB subnet group"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID for RDS placement"
  type        = string
}

variable "db_subnet_ids" {
  description = "Subnet IDs for the DB subnet group"
  type        = list(string)
}

variable "db_username" {
  description = "Master username"
  type        = string
}

variable "db_password" {
  description = "Master password (SOPS-encrypted)"
  type        = string
  sensitive   = true
}

variable "db_encrypted" {
  description = "Whether to enable storage encryption"
  type        = bool
  default     = false
}
