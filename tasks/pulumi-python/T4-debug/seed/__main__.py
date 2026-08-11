import pulumi
import pulumi_aws as aws

# SEED REPO: Pulumi Python with secret read as plain string + .apply() misuse
# Defect 1: Secret read as plain string (should use config.Secret)
# Defect 2: .apply() result used where Output expected

config = pulumi.Config()
env = config.get("env")
region = config.get("region", "us-east-1")

# DESTRUCTIVE CHANGE: password read as plain string instead of Secret
# Should be: db_password = config.require_secret("dbPassword")
db_password = config.get("dbPassword")  # DEFECT: plain string, not a Secret

# S3 Bucket
bucket = aws.s3.Bucket(
    "app-bucket",
    bucket=f"myapp-assets-{env}",
    versioning=aws.s3.BucketVersioningArgs(enabled=True),
    tags={"Environment": env, "Project": "myapp"},
)

# DEFECT: .apply() result used where Output<string> expected
# This crashes because .apply() returns None, not a string
bucket_url = bucket.arn.apply(lambda arn: f"https://s3.{region}.amazonaws.com/{arn}")

# RDS Instance
db = aws.rds.Instance(
    "app-db",
    instance_class="db.t3.medium",
    engine="postgres",
    engine_version="16.1",
    allocated_storage=20,
    db_name="appdb",
    username="app-user",
    password=db_password,
    skip_final_snapshot=True,
    deletion_protection=False,  # Should be True for prod
)

# Output
pulumi.export("bucketUrl", bucket_url)
pulumi.export("dbEndpoint", db.endpoint)
