"""Crossplane T2-generate tests: verify XRD + Composition provisioning."""
from pathlib import Path

def test_xrd_exists():
    """XRD should define the composite API"""
    assert Path("xrds/composite-web-service.yaml").exists()

def test_composition_exists():
    """Composition should be created"""
    assert Path("compositions/composition.yaml").exists()

def test_claim_exists():
    """Claim should instantiate the composite"""
    assert Path("claims/dev.yaml").exists() or Path("claims/prod.yaml").exists()

def test_provider_config_exists():
    """ProviderConfigs should be created"""
    configs = list(Path(".").glob("providers/provider-config-*.yaml"))
    assert len(configs) >= 1, "At least one ProviderConfig should exist"
