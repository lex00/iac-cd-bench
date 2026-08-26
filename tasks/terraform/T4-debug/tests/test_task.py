"""Terraform T4-debug: verify defect fixes.

Locates the HCL by content rather than opening `main.tf` (issue #72): a
model that split its corrected configuration across files, or named it
anything else, previously errored all three assertions out on
FileNotFoundError.

The three assertions are unchanged in substance. NOTE: they are weak --
tests 1 and 2 pass on the *unmodified* seed, since the seed already
contains both `aws_db_instance` and `deletion_protection = false`, and
test 3 ends in a literal `assert True`. That looseness predates this change
and is deliberately left alone here: #72 is about graders that reject
correct answers, and tightening these would silently move every historical
terraform T4 number. It is called out in the PR for a follow-up.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import _grader_lib as gl  # noqa: E402

TFVARS_SUFFIXES = (".tfvars",)


@pytest.fixture(scope="module")
def tf_text() -> str:
    return gl.require_text("the corrected Terraform configuration", ".tf")


@pytest.fixture(scope="module")
def tfvars_text() -> str:
    return "\n".join(
        gl.read_text(p) for p in gl.iter_files(*TFVARS_SUFFIXES)
    )


def test_no_circular_dependency(tf_text):
    """Should not have circular dependency in outputs"""
    # After fix, the output should reference a properly-defined resource
    assert "aws_db_instance" in tf_text


def test_deletion_protection_in_prod(tf_text, tfvars_text):
    """Prod should have deletion_protection = true"""
    if tfvars_text.strip():
        assert "deletion_protection" in tfvars_text.lower() \
            or "deletion_protection" in tf_text.lower()
    else:
        assert "deletion_protection" in tf_text.lower(), \
            "Should mention deletion_protection"


def test_for_each_or_count_consistent(tf_text):
    """Should use either for_each or count consistently, not both"""
    has_for_each = "for_each" in tf_text
    has_count = "count" in tf_text
    # If both are present, it's likely a type mismatch
    if has_for_each and has_count:
        # This is a simplified check - the real issue is using count on a
        # resource that should use for_each or vice versa. Detailed checking
        # would require parsing HCL.
        assert True
