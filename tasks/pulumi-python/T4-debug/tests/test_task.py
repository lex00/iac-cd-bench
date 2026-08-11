"""Pulumi Python T4-debug tests: verify defect fixes."""
from pathlib import Path

def test_secret_not_plain():
    """Password should be read as a Secret, not plain string"""
    with open("__main__.py") as f:
        content = f.read()
    assert "require_secret" in content or "Secret" in content, \
        "Password should be read as a Secret using require_secret()"

def test_apply_not_on_output():
    """Should not misuse .apply() on Output values"""
    with open("__main__.py") as f:
        content = f.read()
    # After fix, should use .apply() properly with a callable
    # or use Output operations directly
    assert content.count(".apply(") <= 2, \
        "Should not overuse .apply() on Output values"
