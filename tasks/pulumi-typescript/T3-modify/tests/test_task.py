"""Semantic grader for pulumi-typescript T3-modify: wrap app-bucket/app-db
in a ComponentResource, aliased so neither is replaced.

cwd is the materialized workspace (the seed's index.ts plus whatever the
model edited/emitted). Reads every *.ts file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _ts_text() -> str:
    parts = []
    for p in sorted(Path(".").rglob("*.ts")):
        try:
            parts.append(p.read_text())
        except Exception:
            continue
    return "\n".join(parts)


def _paren_block(text: str, open_idx: int) -> str:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx : i + 1]
    return text[open_idx:]


def _resource_call(text: str, logical_name: str) -> str:
    """The full `new aws.X.Y("logical_name", {...}, {...})` call, brace/paren
    matched from the constructor's opening paren."""
    m = re.search(rf'new\s+aws\.\w+\.\w+\(\s*["\']{re.escape(logical_name)}["\']', text)
    if not m:
        return ""
    open_idx = text.index("(", m.start())
    return _paren_block(text, open_idx)


@pytest.fixture(scope="module")
def text() -> str:
    return _ts_text()


@pytest.fixture(scope="module")
def bucket_call(text) -> str:
    return _resource_call(text, "app-bucket")


@pytest.fixture(scope="module")
def db_call(text) -> str:
    return _resource_call(text, "app-db")


def test_component_resource_class_defined(text):
    assert re.search(r"extends\s+pulumi\.ComponentResource\b", text), (
        "expected a class extending pulumi.ComponentResource"
    )


def test_bucket_moved_into_component_with_alias(bucket_call):
    assert bucket_call, "expected the app-bucket resource (new aws.s3.Bucket(\"app-bucket\", ...)) to still be present"
    assert re.search(r"parent\s*:\s*this\b", bucket_call), (
        f"app-bucket must be parented to the component (parent: this), got: {bucket_call[:300]!r}"
    )
    assert re.search(r"aliases\s*:\s*\[", bucket_call), (
        f"app-bucket must declare aliases to avoid replacement, got: {bucket_call[:300]!r}"
    )
    assert "app-bucket" in bucket_call, "app-bucket's alias must reference its original logical name"


def test_db_moved_into_component_with_alias(db_call):
    assert db_call, "expected the app-db resource (new aws.rds.Instance(\"app-db\", ...)) to still be present"
    assert re.search(r"parent\s*:\s*this\b", db_call), (
        f"app-db must be parented to the component (parent: this), got: {db_call[:300]!r}"
    )
    assert re.search(r"aliases\s*:\s*\[", db_call), (
        f"app-db must declare aliases to avoid replacement, got: {db_call[:300]!r}"
    )
    assert "app-db" in db_call, "app-db's alias must reference its original logical name"


def test_resource_args_preserved(bucket_call, db_call):
    assert re.search(r"myapp-assets-\$\{env\}", bucket_call), (
        "app-bucket's bucket name template must be unchanged (myapp-assets-${env})"
    )
    assert re.search(r"""instanceClass:\s*["']db\.t3\.medium["']""", db_call), (
        "app-db's instanceClass must be unchanged (db.t3.medium) -- changing it forces replacement"
    )
    assert re.search(r"""engineVersion:\s*["']16\.1["']""", db_call), (
        "app-db's engineVersion must be unchanged (16.1)"
    )
