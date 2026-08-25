"""Semantic grader for pulumi-typescript T4-debug: fix the async/await misuse
on an Output (returns a Promise instead of participating in the Output
chain) and the pulumi.output() wrap of a plaintext password literal.

The originally-shipped grader here matched raw (uncommented) source text, so
both of its checks were satisfiable by the seed's own defect-description
comments: `"async function" not in content or "pulumi.output" not in
content` (comments never mention "pulumi.output" once defect 2 happens to be
fixed, vacuously passing defect 1's check regardless of whether async/await
was actually removed) and `".apply(" in content or "Output." in content`
(the seed's own comment text -- "using await on Output instead of .apply()"
-- contains the literal substring ".apply(", so this passed on the
unmodified seed). This grader strips comments first and checks the two
defects structurally.

cwd is the materialized workspace (the seed's index.ts plus whatever the
model edited/emitted).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _ts_text() -> str:
    parts = []
    for p in sorted(Path(".").rglob("*.ts")):
        try:
            parts.append(_strip_comments(p.read_text()))
        except Exception:
            continue
    return "\n".join(parts)


@pytest.fixture(scope="module")
def text() -> str:
    return _ts_text()


def test_no_async_await_on_output(text):
    assert not re.search(r"async\s+function", text), (
        "expected the async function wrapping the Output await to be removed"
    )
    assert not re.search(r"\bawait\s+\w+\s*;", text), (
        f"expected no `await <Output>;` -- Output values must be resolved via "
        f".apply(), not await, got context: "
        f"{[m.group(0) for m in re.finditer(r'.{0,30}await.{0,30}', text)]!r}"
    )
    assert ".apply(" in text, (
        "expected .apply() to be used to derive bucketUrl from bucket.arn"
    )


def test_password_not_wrapped_plain_string_literal(text):
    assert not re.search(r'pulumi\.output\(\s*["\']', text), (
        "the password must not be a pulumi.output()-wrapped string literal"
    )
    assert re.search(r"config\.requireSecret\(\s*[\"']dbPassword[\"']", text), (
        'expected config.requireSecret("dbPassword") for the password'
    )
    m = re.search(r"new\s+aws\.rds\.Instance\(([^;]*)\);", text, re.DOTALL)
    assert m, "expected a new aws.rds.Instance(...) resource"
    db_block = m.group(1)
    assert re.search(r"password\s*:\s*\w+", db_block), (
        f"expected the RDS instance's password: to reference the requireSecret-derived "
        f"value, got: {db_block[-200:]!r}"
    )
