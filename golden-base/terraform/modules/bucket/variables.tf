variable "bucket_name" {
  description = "Name of the S3 bucket"
  type        = string
}

variable "environment" {
  description = "Environment name (dev | prod)"
  type        = string
}

variable "replication_target_bucket_arn" {
  description = "ARN of the replication target bucket (prod only; empty string for dev)"
  type        = string
  default     = ""
}

variable "replication_role_arn" {
  description = "IAM role ARN for S3 replication (prod only)"
  type        = string
  default     = ""
}
