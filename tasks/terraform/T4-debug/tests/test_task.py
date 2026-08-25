"""Semantic grader for terraform T4-debug: fix the count/for_each type
mismatch (aws_db_instance.main used `count = length(var.envs)`) and the
circular/premature reference in the db_endpoint output (`aws_db_instance
.main[0].endpoint`, a hardcoded integer index that breaks once the resource
is keyed by environment instead of position).

cwd is the materialized workspace (the seed's main.tf plus whatever the model
edited/emitted). Reads every *.tf file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _tf_text() -> str:
    parts = []
    for p in sorted(Path(".").rglob("*.tf")):
        try:
            parts.append(p.read_text())
        except Exception:
            continue
    return "\n".join(parts)


def _blocks(text: str, header_re: str) -> list[str]:
    """Brace-matched bodies for every block whose opening line matches
    header_re (the regex must end just before the opening `{`)."""
    out: list[str] = []
    for m in re.finditer(header_re + r"\s*\{", text):
        start = m.end() - 1
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[start : i + 1])
                    break
    return out


@pytest.fixture(scope="module")
def tf_text() -> str:
    return _tf_text()


@pytest.fixture(scope="module")
def db_instance_blocks(tf_text) -> list[str]:
    return _blocks(tf_text, r'resource\s+"aws_db_instance"\s+"\w+"')


@pytest.fixture(scope="module")
def db_endpoint_output(tf_text) -> str:
    blocks = _blocks(tf_text, r'output\s+"db_endpoint"')
    assert blocks, "expected an output \"db_endpoint\" block"
    return blocks[0]


def test_for_each_replaces_count(db_instance_blocks):
    assert db_instance_blocks, "expected an aws_db_instance resource"
    assert len(db_instance_blocks) == 1, (
        f"expected exactly one aws_db_instance resource, found {len(db_instance_blocks)}"
    )
    body = db_instance_blocks[0]
    assert re.search(r"for_each\s*=", body), (
        "aws_db_instance must use for_each (keyed by environment), not count"
    )
    assert not re.search(r"^\s*count\s*=", body, re.MULTILINE), (
        f"aws_db_instance must not still declare count alongside for_each, got: {body[:400]!r}"
    )


def test_output_not_hardcoded_index(db_endpoint_output):
    assert not re.search(r"aws_db_instance\.\w+\[0\]", db_endpoint_output), (
        f"db_endpoint must not reference the resource with a hardcoded [0] index "
        f"(breaks once the resource is for_each-keyed by environment), got: "
        f"{db_endpoint_output!r}"
    )
    # A for_each-keyed resource is referenced either via a `for` expression
    # over the resource's instances, or via a specific each.key/string index
    # (e.g. aws_db_instance.main["dev"]) -- either is a valid, non-positional
    # reference.
    assert re.search(r"for\s+\w+.*in\s+aws_db_instance\.\w+", db_endpoint_output) or re.search(
        r'aws_db_instance\.\w+\[\s*"[^"]+"\s*\]', db_endpoint_output
    ), (
        f"expected db_endpoint to reference the for_each-keyed resource by "
        f"key (a for-expression over it, or a string-keyed index), got: "
        f"{db_endpoint_output!r}"
    )
