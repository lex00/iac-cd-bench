"""Golden reference implementation of the canonical IaC-CD benchmark scenario.

This stack provisions a stateless web application with supporting infrastructure:
- S3 bucket (versioned, encrypted, no public access)
- RDS PostgreSQL (deletion protection, backup >= 7d, not public)
- IAM user/role for service-account access
- Encrypted secret for DB connection string

Two environments: dev and prod, differentiated via Pulumi stack configs.
"""

from __future__ import annotations

import pulumi
from pulumi import ComponentResource, Config, Output

from components.bucket import S3Bucket
from components.iam import IAMServiceAccount
from components.rds import RDSInstance

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_cfg = Config(__name__)

env = _cfg.get("env", "dev")
region = _cfg.get("aws:region", "us-east-1")

# Application parameters
instance_class = _cfg.get("instance_class", "db.t3.medium")

db_user = _cfg.get("db_user", "app-user")
db_name = _cfg.get("db_name", "appdb")
db_password = _cfg.get_secret("db_password")
bucket_name = _cfg.get("bucket_name", "myapp-assets")

# Prod-specific
replication_target_bucket = _cfg.get("replication_target_bucket")
oidc_provider_arn = _cfg.get("oidc_provider_arn")

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

tags: dict[str, str] = {
    "Project": "iac-cd-bench",
    "Environment": env,
    "ManagedBy": "pulumi",
}


class ApplicationStack(ComponentResource):
    """Top-level component that wires S3 + RDS + IAM for the canonical scenario."""

    def __init__(self, name: str) -> None:
        super().__init__("iac-cd-bench:ApplicationStack", name, None, None)

        is_prod = env == "prod"

        # ------------------------------------------------------------------
        # S3 Bucket
        # ------------------------------------------------------------------
        self.bucket = S3Bucket(
            f"{name}-bucket",
            bucket_name=bucket_name,
            tags=tags,
            enable_replication=is_prod,
            replication_target_bucket=replication_target_bucket,
        )

        # ------------------------------------------------------------------
        # RDS Instance
        # ------------------------------------------------------------------
        db_password_resolved = (
            db_password if db_password is not None else "placeholder"
        )

        self.rds = RDSInstance(
            f"{name}-rds",
            db_name=db_name,
            db_user=db_user,
            db_password=db_password_resolved,
            instance_class=instance_class,
            allocated_storage=20,
            multi_az=is_prod,
            storage_encrypted=is_prod,
            backup_retention_days=7,
            tags=tags,
        )

        # ------------------------------------------------------------------
        # IAM Service Account
        # ------------------------------------------------------------------
        if is_prod:
            # Build least-privilege ARN list from bucket outputs
            # For inline policies, use concrete ARN strings where possible
            bucket_arn_str: str = bucket_name
            allowed_arns_prod: list[str] = [
                f"arn:aws:s3:::{bucket_arn_str}",
                f"arn:aws:s3:::{bucket_arn_str}/*",
            ]

            self.iam = IAMServiceAccount(
                f"{name}-iam",
                create_user=False,
                create_role=True,
                allowed_arns=allowed_arns_prod,
                oidc_provider_arn=oidc_provider_arn,
                tags=tags,
            )
        else:
            # Dev: programmatic access user
            self.iam = IAMServiceAccount(
                f"{name}-iam",
                create_user=True,
                create_role=False,
                tags=tags,
            )

        # ------------------------------------------------------------------
        # Secret: DB connection string (encrypted at rest via ConfigSecret)
        # ------------------------------------------------------------------
        db_password_for_uri = (
            db_password if db_password is not None else "placeholder"
        )
        self.db_connection_string: Output[str] = (
            pulumi.Output.concat(
                "postgresql://",
                db_user,
                ":",
                db_password_for_uri,
                "@",
                self.rds.address,
                ":",
                self.rds.port.apply(lambda p: str(p)),
                "/",
                db_name,
            )
        )

        # ------------------------------------------------------------------
        # Register outputs
        # ------------------------------------------------------------------
        self.register_outputs(
            {
                "bucket_id": self.bucket.bucket_id,
                "bucket_arn": self.bucket.bucket_arn,
                "rds_endpoint": self.rds.endpoint,
                "db_connection_string": self.db_connection_string,
                "environment": env,
            }
        )


# ---------------------------------------------------------------------------
# Stack composition
# ---------------------------------------------------------------------------

stack = ApplicationStack("app-stack")

# Export stack-level outputs
pulumi.export("bucket_id", stack.bucket.bucket_id)
pulumi.export("bucket_arn", stack.bucket.bucket_arn)
pulumi.export("rds_endpoint", stack.rds.endpoint)
pulumi.export("db_connection_string", stack.db_connection_string)
pulumi.export("environment", env)
