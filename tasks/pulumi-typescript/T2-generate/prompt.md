## Task: Create ComponentResource wrapping service + bucket + DB

**Stack:** Pulumi (TypeScript)

Create a ComponentResource that wraps:
1. S3 bucket with versioning and encryption
2. RDS PostgreSQL instance with deletion protection
3. IAM role for service accounts

Use Pulumi TypeScript SDK. Support dev/prod via stack config.

{{scenario_spec}}
