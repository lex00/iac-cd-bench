"""Semantic coverage grader for chant T2-generate.

Greps the model's emitted TypeScript for the required composite invocations
and props: a new SecureBucket call for myapp-logs-{env} and a ReaderIam call
scoped ONLY to that bucket, added independently to both dev and prod. There
is no build step here -- models emit source, and this grader checks the
source directly, the same way the other T2-generate graders check emitted
YAML/HCL.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _all_ts_files() -> list[Path]:
    return sorted(Path(".").rglob("*.ts"))


def _all_ts_text() -> str:
    chunks = []
    for p in _all_ts_files():
        try:
            chunks.append(p.read_text())
        except Exception:
            continue
    return "\n---\n".join(chunks)


def _reader_iam_blocks(text: str) -> list[str]:
    """Extract the prop-object body of every ReaderIam({...}) call site."""
    blocks = []
    for m in re.finditer(r"ReaderIam\(\s*\{", text):
        start = m.end() - 1  # position of the opening brace
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(text[start : i + 1])
                    break
    return blocks


def _secure_bucket_blocks(text: str) -> list[str]:
    blocks = []
    for m in re.finditer(r"SecureBucket\(\s*\{", text):
        start = m.end() - 1
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(text[start : i + 1])
                    break
    return blocks


@pytest.fixture(scope="module")
def all_text() -> str:
    return _all_ts_text()


@pytest.fixture(scope="module")
def secure_bucket_blocks(all_text) -> list[str]:
    return _secure_bucket_blocks(all_text)


@pytest.fixture(scope="module")
def reader_iam_blocks(all_text) -> list[str]:
    return _reader_iam_blocks(all_text)


def test_dev_logs_bucket_via_composite(secure_bucket_blocks):
    """A SecureBucket({...}) call site must declare myapp-logs-dev."""
    hits = [b for b in secure_bucket_blocks if "myapp-logs-dev" in b]
    assert hits, "expected a SecureBucket({...}) call declaring myapp-logs-dev"


def test_prod_logs_bucket_via_composite(secure_bucket_blocks):
    """A SecureBucket({...}) call site must declare myapp-logs-prod."""
    hits = [b for b in secure_bucket_blocks if "myapp-logs-prod" in b]
    assert hits, "expected a SecureBucket({...}) call declaring myapp-logs-prod"


def test_no_raw_bucket_bypass(all_text):
    """The logs buckets must go through SecureBucket, not a raw S3Bucket(...)."""
    # A raw bypass would construct `new S3Bucket({... name: "myapp-logs-..."})`
    # without ever calling SecureBucket for that name.
    raw_s3_blocks = []
    for m in re.finditer(r"new S3Bucket\(\s*\{", all_text):
        start = m.end() - 1
        depth = 0
        for i in range(start, len(all_text)):
            if all_text[i] == "{":
                depth += 1
            elif all_text[i] == "}":
                depth -= 1
                if depth == 0:
                    raw_s3_blocks.append(all_text[start : i + 1])
                    break
    bypassed = [b for b in raw_s3_blocks if "myapp-logs-" in b]
    assert not bypassed, (
        "myapp-logs bucket(s) must be declared via the SecureBucket composite, "
        "not a raw `new S3Bucket({...})` call"
    )


def test_dev_logs_reader_scoped(reader_iam_blocks):
    """A ReaderIam({...}) call scoped to myapp-logs-dev must grant PutObject."""
    hits = [
        b for b in reader_iam_blocks
        if "myapp-logs-dev" in b and "bucketName" in b
    ]
    assert hits, "expected a ReaderIam({...}) call with bucketName myapp-logs-dev"
    assert any("PutObject" in b for b in hits), (
        "the myapp-logs-dev reader must grant s3:PutObject (via additionalActions)"
    )
    # Must not also target the assets bucket in the same call (no crosstalk).
    assert not any("myapp-assets-dev" in b for b in hits), (
        "the myapp-logs-dev reader must not also reference myapp-assets-dev"
    )


def test_prod_logs_reader_scoped(reader_iam_blocks):
    """A ReaderIam({...}) call scoped to myapp-logs-prod must grant PutObject."""
    hits = [
        b for b in reader_iam_blocks
        if "myapp-logs-prod" in b and "bucketName" in b
    ]
    assert hits, "expected a ReaderIam({...}) call with bucketName myapp-logs-prod"
    assert any("PutObject" in b for b in hits), (
        "the myapp-logs-prod reader must grant s3:PutObject (via additionalActions)"
    )
    assert not any("myapp-assets-prod" in b for b in hits), (
        "the myapp-logs-prod reader must not also reference myapp-assets-prod"
    )


def test_no_wildcard_actions(all_text):
    """Nowhere in the emitted source should an IAM action be a wildcard."""
    assert not re.search(r"""["']s3:\*["']""", all_text), (
        "found a wildcard S3 action (s3:*) -- SPEC criterion 4 requires "
        "enumerated actions, never a wildcard"
    )
    assert not re.search(r"""Action:\s*["']\*["']""", all_text), (
        "found a bare wildcard IAM action"
    )
