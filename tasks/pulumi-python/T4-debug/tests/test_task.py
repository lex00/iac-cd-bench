"""Semantic grader for pulumi-python T4-debug: fix the plain-string secret
read and the disabled deletion_protection on the prod RDS instance.

The originally-shipped grader here checked `"require_secret" in content or
"Secret" in content` (satisfied by the seed's own comment mentioning
`config.require_secret`, and by the `BucketVersioningArgs`/`import
pulumi_aws as aws` boilerplate containing "S3" and "Secret"-adjacent text is
not actually present, but the check was still a loose OR) and `.apply(") <=
2` (a token-count heuristic unrelated to the actual defect, which was never a
real .apply() misuse -- see the corrected `defect:` in spec.yaml). This
grader instead checks the two real defects structurally.

cwd is the materialized workspace (the seed's __main__.py plus whatever the
model edited/emitted).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _py_text() -> str:
    parts = []
    for p in sorted(Path(".").rglob("*.py")):
        try:
            parts.append(p.read_text())
        except Exception:
            continue
    return "\n".join(parts)


@pytest.fixture(scope="module")
def text() -> str:
    return _py_text()


def test_password_read_as_secret(text):
    assert not re.search(r'db_password\s*=\s*config\.get\(\s*["\']dbPassword["\']', text), (
        "db_password must not be read via config.get(\"dbPassword\") (plain string)"
    )
    assert re.search(
        r'db_password\s*=\s*config\.require_secret\(\s*["\']dbPassword["\']', text
    ), (
        'expected db_password = config.require_secret("dbPassword")'
    )
    # And the fixed secret must actually be what's passed to the RDS instance.
    m = re.search(r"aws\.rds\.Instance\(.*?\)\s*$", text, re.DOTALL | re.MULTILINE)
    db_block = m.group(0) if m else text
    assert re.search(r"password\s*=\s*db_password\b", db_block), (
        "expected the RDS instance's password= to still be db_password (now a Secret)"
    )


def test_deletion_protection_enabled(text):
    m = re.search(r"aws\.rds\.Instance\(([^)]*(?:\)[^)]*)*)\)", text, re.DOTALL)
    assert m, "expected an aws.rds.Instance(...) resource"
    body = m.group(1)
    assert not re.search(r"deletion_protection\s*=\s*False\b", body), (
        f"deletion_protection must not be False, got: {body[-200:]!r}"
    )
    assert re.search(r"deletion_protection\s*=\s*True\b", body), (
        f"expected deletion_protection=True on the RDS instance, got: {body[-200:]!r}"
    )
