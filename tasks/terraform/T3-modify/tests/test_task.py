"""Semantic grader for terraform T3-modify: collapse the seed's duplicated
aws_eks_node_group.dev / aws_eks_node_group.prod blocks into one resource
driven by for_each, with zero-diff `moved` blocks for the state migration.

cwd is the materialized workspace (the seed's main.tf plus whatever the model
edited/emitted). Reads every *.tf file rather than assuming main.tf specifically,
since a model may split the refactor into a separate file.
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


def _resource_blocks(text: str, resource_type: str) -> list[tuple[str, str]]:
    """[(label, body)] for every `resource "<resource_type>" "<label>" { ... }`
    block, brace-matched (not regex-bounded, since scaling_config nests braces)."""
    out: list[tuple[str, str]] = []
    for m in re.finditer(rf'resource\s+"{re.escape(resource_type)}"\s+"(\w+)"\s*\{{', text):
        label = m.group(1)
        start = m.end() - 1
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append((label, text[start : i + 1]))
                    break
    return out


@pytest.fixture(scope="module")
def tf_text() -> str:
    return _tf_text()


@pytest.fixture(scope="module")
def node_group_blocks(tf_text):
    return _resource_blocks(tf_text, "aws_eks_node_group")


def test_single_for_each_node_group_resource(node_group_blocks):
    assert len(node_group_blocks) == 1, (
        f"expected exactly one aws_eks_node_group resource (for_each-driven), "
        f"found {len(node_group_blocks)}: {[label for label, _ in node_group_blocks]!r}"
    )
    _label, body = node_group_blocks[0]
    assert re.search(r"for_each\s*=", body), (
        "the single aws_eks_node_group resource must use for_each"
    )


def test_dev_sizing_preserved(tf_text):
    assert re.search(r't3\.medium', tf_text), "dev's t3.medium instance type must be preserved"
    assert re.search(r"desired_size\s*=\s*2\b", tf_text), "dev's desired_size = 2 must be preserved"
    assert re.search(r"min_size\s*=\s*1\b", tf_text), "dev's min_size = 1 must be preserved"
    assert re.search(r"max_size\s*=\s*3\b", tf_text), "dev's max_size = 3 must be preserved"


def test_prod_sizing_preserved(tf_text):
    assert re.search(r't3\.large', tf_text), "prod's t3.large instance type must be preserved"
    assert re.search(r"desired_size\s*=\s*4\b", tf_text), "prod's desired_size = 4 must be preserved"
    assert re.search(r"min_size\s*=\s*2\b", tf_text), "prod's min_size = 2 must be preserved"
    assert re.search(r"max_size\s*=\s*6\b", tf_text), "prod's max_size = 6 must be preserved"


def test_moved_blocks_cover_both_old_addresses(tf_text):
    moved_blocks = re.findall(r"moved\s*\{([^}]*)\}", tf_text, re.DOTALL)
    assert moved_blocks, "expected `moved` blocks for zero-diff state migration"
    combined = "\n".join(moved_blocks)
    assert re.search(r"from\s*=\s*aws_eks_node_group\.dev\b", combined), (
        "expected a `moved` block with from = aws_eks_node_group.dev"
    )
    assert re.search(r"from\s*=\s*aws_eks_node_group\.prod\b", combined), (
        "expected a `moved` block with from = aws_eks_node_group.prod"
    )
    assert re.search(r"to\s*=\s*aws_eks_node_group\.\w+\[", combined), (
        "expected the `moved` block(s) `to` target to index into the new for_each resource"
    )
