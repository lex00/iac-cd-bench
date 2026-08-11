import pytest
from pathlib import Path

def test_bucket_manifest_exists():
    """S3 bucket manifest should be created"""
    bucket_yaml = Path("infra/s3/logs-bucket.yaml")
    assert bucket_yaml.exists(), "logs bucket manifest should exist"

def test_bucket_versioning():
    """Bucket should have versioning enabled"""
    bucket_yaml = Path("infra/s3/logs-bucket.yaml")
    content = bucket_yaml.read_text()
    assert "VersioningConfiguration" in content
    assert "Enabled" in content

def test_bucket_encryption():
    """Bucket should have server-side encryption"""
    bucket_yaml = Path("infra/s3/logs-bucket.yaml")
    content = bucket_yaml.read_text()
    assert "ServerSideEncryption" in content or "sseAlgorithm" in content
    assert "AES256" in content or "AES256" in content

def test_public_access_blocked():
    """Bucket should have public access blocked"""
    bucket_yaml = Path("infra/s3/logs-bucket.yaml")
    content = bucket_yaml.read_text()
    assert "PublicAccessBlock" in content or "blockPublic" in content

def test_iam_role_created():
    """IRSA role should be created"""
    iam_dir = Path("infra/iam/")
    role_files = list(iam_dir.glob("*logs*"))
    assert len(role_files) > 0, "Should have IAM role for IRSA"

def test_flux_kustomization_added():
    """Flux kustomization should reference logs bucket"""
    flux_file = Path("flux/kustomizations.yaml")
    content = flux_file.read_text()
    assert "logs" in content or "logs-bucket" in content
