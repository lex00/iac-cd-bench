"""Semantic grader for crossplane T4-debug: fix the wrong fromFieldPath
(spec.parameters.storageClass -> spec.parameters.instanceClass) and add real
ReadinessChecks so the Composition reaches Ready.

Parses composition.yaml structurally (not a substring search) -- the seed's
own defect-description comments contain the literal strings
"spec.parameters.instanceClass" and "ReadinessChecks", so a naive `"..." in
content` check passes on the unmodified seed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def _composition() -> dict:
    hits = [
        p for p in Path(".").rglob("*.yaml")
        if p.name != "xrd.yaml"
    ]
    for p in hits:
        try:
            for doc in yaml.safe_load_all(p.read_text()):
                if isinstance(doc, dict) and doc.get("kind") == "Composition":
                    return doc
        except yaml.YAMLError:
            continue
    return {}


@pytest.fixture(scope="module")
def composition() -> dict:
    return _composition()


@pytest.fixture(scope="module")
def rds_resource(composition) -> dict:
    resources = composition.get("spec", {}).get("resources", []) or []
    rds = [r for r in resources if r.get("name") == "rds-instance"]
    assert rds, "expected the rds-instance resource entry in composition.yaml"
    return rds[0]


def test_instance_class_field_path_fixed(rds_resource):
    patches = rds_resource.get("patches") or []
    to_instance_class = [
        p for p in patches
        if p.get("toFieldPath") == "spec.forProvider.instanceClass"
    ]
    assert to_instance_class, (
        "expected a patch with toFieldPath: spec.forProvider.instanceClass"
    )
    assert any(
        p.get("fromFieldPath") == "spec.parameters.instanceClass"
        for p in to_instance_class
    ), (
        f"expected fromFieldPath: spec.parameters.instanceClass, got: "
        f"{[p.get('fromFieldPath') for p in to_instance_class]!r}"
    )


def test_readiness_checks_defined(rds_resource):
    readiness = rds_resource.get("readiness")
    assert readiness, "expected spec.resources[rds-instance].readiness to be non-empty"
    assert isinstance(readiness, dict), f"expected readiness to be a mapping, got: {readiness!r}"
    checks = readiness.get("checks")
    assert checks, (
        f"expected readiness.checks to be a non-empty list of ReadinessChecks, got: {readiness!r}"
    )
