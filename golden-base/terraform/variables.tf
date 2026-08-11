# =============================================================================
# Root module variables - canonical scenario
# =============================================================================

variable "region" {
  description = "AWS region for primary resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev | prod)"
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "Environment must be 'dev' or 'prod'."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
  default     = "canonical-cluster"
}

variable "instance_type" {
  description = "EC2 instance type for EKS node group"
  type        = string
  default     = "t3.medium"
}

variable "desired_nodes" {
  description = "Number of desired nodes in the EKS managed node group"
  type        = number
  default     = 2
}

variable "multi_az" {
  description = "Whether to deploy RDS across multiple AZs"
  type        = bool
  default     = false
}

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "rds_allocated_storage" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 20
}

variable "rds_backup_retention_days" {
  description = "RDS backup retention period in days (minimum 7)"
  type        = number
  default     = 7

  validation {
    condition     = var.rds_backup_retention_days >= 7
    error_message = "Backup retention must be at least 7 days."
  }
}

variable "s3_bucket_name" {
  description = "Name of the application assets S3 bucket"
  type        = string
  default     = "canonical-app-assets"
}

variable "s3_replication_target_region" {
  description = "Target region for S3 cross-region replication (used in prod)"
  type        = string
  default     = ""
}

variable "db_username" {
  description = "Master username for the RDS instance"
  type        = string
}

variable "db_password" {
  description = "Master password for the RDS instance (SOPS-encrypted at rest)"
  type        = string
  sensitive   = true
}

variable "enable_cloudfront" {
  description = "Whether to provision CloudFront + ACM (true in prod, false in dev)"
  type        = bool
  default     = false
}

# =============================================================================
# Terraform backend - remote state in S3 + DynamoDB
# =============================================================================

variable "state_bucket_name" {
  description = "S3 bucket for Terraform state"
  type        = string
  default     = "terraform-state-canonical"
}

variable "state_dynamodb_table" {
  description = "DynamoDB table for state locking"
  type        = string
  default     = "terraform-state-locks"
}
