"""Crossplane T4-debug tests: verify defect fixes."""
from pathlib import Path

def test_composition_has_correct_field_path():
    """Composition should reference spec.parameters.instanceClass"""
    with open("composition.yaml") as f:
        content = f.read()
    assert "spec.parameters.instanceClass" in content, \
        "Should use spec.parameters.instanceClass instead of spec.parameters.storageClass"

def test_composition_has_readiness_checks():
    """Composition should have ReadinessChecks on RDS resource"""
    with open("composition.yaml") as f:
        content = f.read()
    assert "readiness" in content and ("ReadinessChecks" in content or "checkType" in content), \
        "Composition should have ReadinessChecks defined"
