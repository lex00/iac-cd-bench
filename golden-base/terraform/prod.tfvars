# =============================================================================
# Prod environment configuration
# =============================================================================

region      = "us-east-1"
environment = "prod"

# EKS
instance_type = "t3.large"
desired_nodes = 4

# RDS - multi-AZ, encrypted
rds_instance_class        = "db.t3.medium"
rds_allocated_storage     = 100
rds_backup_retention_days = 14
multi_az                  = true

# S3 with cross-region replication
s3_bucket_name               = "canonical-app-assets-prod"
s3_replication_target_region = "us-west-2"

# HTTPS - CloudFront + ACM
enable_cloudfront = true

# Secrets (SOPS-encrypted; these placeholders are for documentation)
# In production use, these are populated from secrets.tfvars.auto.enc
db_username = "admin"
db_password = ""
