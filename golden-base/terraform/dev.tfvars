# =============================================================================
# Dev environment configuration
# =============================================================================

region      = "us-east-1"
environment = "dev"

# EKS
instance_type = "t3.medium"
desired_nodes = 2

# RDS
rds_instance_class        = "db.t3.micro"
rds_allocated_storage     = 20
rds_backup_retention_days = 7
multi_az                  = false

# S3
s3_bucket_name = "canonical-app-assets-dev"
# No replication in dev

# HTTPS - internal ALB only (no CloudFront)
enable_cloudfront = false

# Secrets (SOPS-encrypted; these placeholders are for documentation)
# In production use, these are populated from secrets.tfvars.auto.enc
db_username = "admin"
db_password = ""
