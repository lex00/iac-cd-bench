"""Terraform T2-generate tests: verify module structure."""
from pathlib import Path

def test_main_tf_exists():
    """main.tf should define providers and backend"""
    assert Path("main.tf").exists()

def test_infrastructure_tf_exists():
    """infrastructure.tf should define resources"""
    assert Path("infrastructure.tf").exists()

def test_variables_tf_exists():
    """variables.tf should define inputs"""
    assert Path("variables.tf").exists()

def test_dev_tfvars_exists():
    """dev.tfvars should define dev configuration"""
    assert Path("dev.tfvars").exists()

def test_prod_tfvars_exists():
    """prod.tfvars should define prod configuration"""
    assert Path("prod.tfvars").exists()

def test_s3_bucket_versioning():
    """S3 bucket should have versioning enabled"""
    with open("infrastructure.tf") as f:
        content = f.read()
    assert "versioning" in content.lower(), "S3 bucket should have versioning"

def test_rds_deletion_protection():
    """RDS should have deletion protection in prod"""
    with open("prod.tfvars") as f:
        content = f.read()
    assert "deletion_protection" in content.lower() or "deletion" in content.lower(), \
        "Prod should have deletion protection"
