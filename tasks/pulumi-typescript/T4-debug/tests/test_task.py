"""Pulumi TypeScript T4-debug tests: verify defect fixes."""
from pathlib import Path

def test_no_async_in_index():
    """Should not have async functions that return Promises for Outputs"""
    with open("index.ts") as f:
        content = f.read()
    # After fix, should use .apply() instead of async/await for Outputs
    assert "async function" not in content or "pulumi.output" not in content, \
        "Should not mix async functions with pulumi.output() wrapping"

def test_proper_output_handling():
    """Should use .apply() for Output transformations"""
    with open("index.ts") as f:
        content = f.read()
    # Should have .apply() for proper Output handling
    assert ".apply(" in content or "Output." in content, \
        "Should use .apply() or Output operations for transformations"
