"""Pulumi program — artifact storage + app role (pulumi-python T6 seed)."""

import json

import pulumi
import pulumi_aws as aws

config = pulumi.Config()
env = config.require("env")
replicas = config.get_int("replicas") or 2
db_password = config.require_secret("dbPassword")

artifacts = aws.s3.Bucket(
    "artifacts",
    bucket=f"knr-artifacts-{env}",
    versioning=aws.s3.BucketVersioningArgs(enabled=True),
    tags={"Env": env},
    opts=pulumi.ResourceOptions(protect=True),
)

logs = aws.s3.Bucket(
    "logs",
    bucket=f"knr-logs-{env}",
    opts=pulumi.ResourceOptions(
        delete_before_replace=True,
        depends_on=[artifacts],
    ),
)

role = aws.iam.Role(
    "app-role",
    assume_role_policy=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }),
)

# Policy references the bucket ARN — an Output
policy = aws.iam.RolePolicy(
    "app-policy",
    role=role.id,
    policy=artifacts.arn.apply(lambda arn: json.dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject"],
            "Resource": f"{arn}/*",
        }],
    })),
)

secret_param = aws.ssm.Parameter(
    "db-password",
    type="SecureString",
    value=db_password,
)

pulumi.export("bucket_name", artifacts.bucket)
pulumi.export("bucket_arn", artifacts.arn)
pulumi.export("db_password_plain", db_password)
