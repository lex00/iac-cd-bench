variable "environment" {
  description = "Environment name (dev | prod)"
  type        = string
}

variable "cluster_oidc_issuer" {
  description = "OIDC issuer URL of the EKS cluster (for IAM role trust)"
  type        = string
  default     = ""
}

variable "iam_role_name" {
  description = "Name of the IAM role for the application service account"
  type        = string
  default     = "canonical-app-role"
}

variable "iam_user_name" {
  description = "Name of the IAM user for programmatic access"
  type        = string
  default     = "canonical-app-user"
}

variable "enable_oidc_trust" {
  description = "Whether to configure OIDC trust for the IAM role (prod)"
  type        = bool
  default     = false
}
