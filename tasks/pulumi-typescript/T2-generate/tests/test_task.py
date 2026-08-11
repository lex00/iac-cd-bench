"""Pulumi TypeScript T2-generate tests: verify ComponentResource structure."""
from pathlib import Path

def test_index_exists():
    """index.ts should exist"""
    assert Path("index.ts").exists()

def test_components_dir():
    """Components directory should exist"""
    assert Path("components").is_dir()

def test_bucket_component():
    """S3 bucket component should be created"""
    assert Path("components/bucket.ts").exists()

def test_rds_component():
    """RDS component should be created"""
    assert Path("components/rds.ts").exists()

def test_bucket_versioning():
    """Bucket component should enable versioning"""
    with open("components/bucket.ts") as f:
        content = f.read()
    assert "versioning" in content.lower() or "Versioning" in content

def test_rds_deletion_protection():
    """RDS component should support deletion protection"""
    with open("components/rds.ts") as f:
        content = f.read()
    assert "deletionProtection" in content or "deletion_protection" in content.lower()
