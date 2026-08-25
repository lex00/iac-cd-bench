"""Semantic grader for bare T4-debug: Deployment selector/template mismatch.

Accepts either valid fix strategy (add the missing label to the template,
or drop it from the selector) by checking the actual Kubernetes validation
rule directly: every key/value pair in spec.selector.matchLabels must also
appear in spec.template.metadata.labels. Also checks the Service still
selects the (fixed) pods.
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
def prod_docs():
    return _load_docs(Path("prod/app.yaml"))


def test_selector_matches_template_labels(prod_docs):
    """The actual Kubernetes API server rule: selector must be a subset of
    the pod template's labels, or the object is rejected on apply."""
    deploy = _find(prod_docs, "Deployment", "myapp-prod")
    assert deploy is not None, "prod/app.yaml: myapp-prod Deployment not found"
    selector = deploy["spec"]["selector"]["matchLabels"]
    template_labels = deploy["spec"]["template"]["metadata"]["labels"]
    missing = {k: v for k, v in selector.items() if template_labels.get(k) != v}
    assert not missing, (
        f"Deployment selector requires labels not present on the pod template: {missing!r} "
        f"-- kubectl apply would still be rejected"
    )
    # Sanity: the fix shouldn't have gutted the original identifying labels
    assert selector.get("app") == "myapp" and selector.get("env") == "prod"


def test_service_still_selects_pods(prod_docs):
    """The Service's selector must remain satisfied by the (fixed) template labels."""
    deploy = _find(prod_docs, "Deployment", "myapp-prod")
    svc = _find(prod_docs, "Service", "myapp-prod")
    assert deploy is not None and svc is not None, "prod/app.yaml: Deployment or Service missing"
    template_labels = deploy["spec"]["template"]["metadata"]["labels"]
    svc_selector = svc["spec"]["selector"]
    missing = {k: v for k, v in svc_selector.items() if template_labels.get(k) != v}
    assert not missing, f"Service selector no longer matches pod template labels: {missing!r}"
