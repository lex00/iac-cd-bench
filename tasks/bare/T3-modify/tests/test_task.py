"""Semantic grader for bare T3-modify: scale workers in both dev and prod.

bare has no shared base/overlay, so the fix must land in BOTH
dev/workers.yaml and prod/workers.yaml independently -- this grader asserts
each environment separately rather than accepting a change in only one.
"""

from pathlib import Path

import pytest
import yaml


def _load_docs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _find(docs: list[dict], kind: str, name: str) -> dict | None:
    for d in docs:
        if d.get("kind") == kind and d.get("metadata", {}).get("name") == name:
            return d
    return None


@pytest.fixture(scope="module")
def dev_docs():
    return _load_docs(Path("dev/workers.yaml"))


@pytest.fixture(scope="module")
def prod_docs():
    return _load_docs(Path("prod/workers.yaml"))


def test_dev_replicas_scaled(dev_docs):
    md = _find(dev_docs, "MachineDeployment", "myapp-dev-workers")
    assert md is not None, "dev/workers.yaml: myapp-dev-workers MachineDeployment not found"
    assert md["spec"]["replicas"] == 3, \
        f"dev replicas: expected 3, got {md['spec'].get('replicas')!r}"


def test_dev_instance_type_unchanged(dev_docs):
    tmpl = _find(dev_docs, "AWSMachineTemplate", "myapp-dev-workers")
    assert tmpl is not None, "dev/workers.yaml: myapp-dev-workers AWSMachineTemplate not found"
    itype = tmpl["spec"]["template"]["spec"]["instanceType"]
    assert itype == "t3.medium", f"dev instanceType should stay t3.medium, got {itype!r}"


def test_prod_replicas_scaled(prod_docs):
    md = _find(prod_docs, "MachineDeployment", "myapp-prod-workers")
    assert md is not None, "prod/workers.yaml: myapp-prod-workers MachineDeployment not found"
    assert md["spec"]["replicas"] == 6, \
        f"prod replicas: expected 6, got {md['spec'].get('replicas')!r}"


def test_prod_instance_type_unchanged(prod_docs):
    tmpl = _find(prod_docs, "AWSMachineTemplate", "myapp-prod-workers")
    assert tmpl is not None, "prod/workers.yaml: myapp-prod-workers AWSMachineTemplate not found"
    itype = tmpl["spec"]["template"]["spec"]["instanceType"]
    assert itype == "t3.large", f"prod instanceType should stay t3.large, got {itype!r}"
