## Task: Create Terraform module for bucket + RDS

**Stack:** Terraform

Create a Terraform module that provisions:
1. S3 bucket with versioning and encryption
2. RDS PostgreSQL instance with deletion protection
3. IAM role for service accounts

Use Terraform modules with variables/outputs. Support dev/prod via workspaces or tfvars.

{{scenario_spec}}
