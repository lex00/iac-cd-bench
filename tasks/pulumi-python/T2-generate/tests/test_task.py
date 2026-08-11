"""Pulumi Python T2-generate tests: verify ComponentResource structure."""
from pathlib import Path

def test_main_exists():
    """__main__.py should exist"""
    assert Path("__main__.py").exists()

def test_components_dir():
    """Components directory should exist"""
    assert Path("components").is_dir()

def test_bucket_component():
    """S3 bucket component should be created"""
    assert Path("components/bucket.py").exists()

def test_rds_component():
    """RDS component should be created"""
    assert Path("components/rds.py").exists()

def test_bucket_versioning():
    """Bucket component should enable versioning"""
    with open("components/bucket.py") as f:
        content = f.read()
    assert "versioning" in content.lower() or "Versioning" in content

def test_rds_deletion_protection():
    """RDS component should support deletion protection"""
    with open("components/rds.py") as f:
        content = f.read()
    assert "deletion_protection" in content.lower() or "DeletionProtection" in content
