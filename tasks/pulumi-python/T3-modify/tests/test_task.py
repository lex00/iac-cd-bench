"""Semantic grader for pulumi-python T3-modify: add a scaling policy for the
seed's app-asg Auto Scaling Group without replacing it.

cwd is the materialized workspace (the seed's __main__.py plus whatever the
model edited/emitted). Reads every *.py file, since a model may put the new
policy in a separate module.
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


def test_existing_asg_args_unchanged(text):
    # The seed's fixed identity/capacity args -- any of these being edited
    # would force replacement of app-asg.
    assert re.search(r'"myapp-\{env\}-asg"|f"myapp-\{env\}-asg"', text), (
        "app-asg's physical name must be unchanged (myapp-{env}-asg)"
    )
    assert re.search(r"min_size\s*=\s*2\b", text), "app-asg's min_size=2 must be unchanged"
    assert re.search(r"max_size\s*=\s*6\b", text), "app-asg's max_size=6 must be unchanged"
    assert re.search(r"desired_capacity\s*=\s*2\b", text), (
        "app-asg's desired_capacity=2 must be unchanged"
    )
    assert re.search(r'"lt-0123456789abcdef0"', text), (
        "app-asg's launch_template id must be unchanged"
    )


def test_single_asg_resource(text):
    # Exactly one autoscaling.Group -- the model must not have recreated
    # app-asg under a new logical name (which would replace it) or duplicated it.
    hits = re.findall(r"aws\.autoscaling\.Group\(\s*\n?\s*[\"']([^\"']+)[\"']", text)
    assert hits, "expected the existing aws.autoscaling.Group resource to still be present"
    assert len(hits) == 1, f"expected exactly one autoscaling.Group, found: {hits!r}"
    assert hits[0] == "app-asg", f"expected the ASG's logical name to remain app-asg, got {hits[0]!r}"


def test_scaling_policy_added(text):
    assert re.search(r"aws\.autoscaling\.Policy\(", text), (
        "expected a new aws.autoscaling.Policy resource"
    )


def test_policy_targets_existing_group(text):
    # Grab the Policy(...) call site and confirm it references app_asg's name,
    # not a hardcoded/duplicated group.
    m = re.search(r"aws\.autoscaling\.Policy\((.*?)\n\)", text, re.DOTALL)
    assert m, "could not locate the aws.autoscaling.Policy(...) call body"
    body = m.group(1)
    assert re.search(r"autoscaling_group_name\s*=\s*app_asg\.name", body), (
        f"expected autoscaling_group_name=app_asg.name, got: {body[:300]!r}"
    )
    assert re.search(r"policy_type\s*=|scaling_adjustment\s*=|step_adjustments\s*=", body), (
        "expected the policy to actually configure a scaling strategy "
        "(policy_type / scaling_adjustment / step_adjustments)"
    )
