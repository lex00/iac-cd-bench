"""Semantic grader for crossplane T3-modify: add a us-west-2 ProviderConfig
and wire a new composition resource to it, without touching the existing
s3-bucket resource or the existing claim.

cwd is the materialized workspace (the seed's provider-config.yaml,
composition.yaml, claim.yaml, plus whatever the model edited/emitted). Reads
every *.yaml/*.yml file and parses each as a (possibly multi-doc) stream of
Kubernetes-style manifests, tolerant of the model splitting resources across
files differently than the seed did.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def _all_docs() -> list[dict]:
    docs: list[dict] = []
    for p in sorted(list(Path(".").rglob("*.yaml")) + list(Path(".").rglob("*.yml"))):
        try:
            text = p.read_text()
        except Exception:
            continue
        try:
            for doc in yaml.safe_load_all(text):
                if isinstance(doc, dict):
                    docs.append(doc)
        except yaml.YAMLError:
            continue
    return docs


def _by_kind(docs: list[dict], kind: str) -> list[dict]:
    return [d for d in docs if d.get("kind") == kind]


def _pipeline_resources(composition: dict) -> list[dict]:
    resources: list[dict] = []
    for step in composition.get("spec", {}).get("pipeline", []) or []:
        inp = step.get("input") or {}
        resources.extend(inp.get("resources") or [])
    return resources


@pytest.fixture(scope="module")
def docs() -> list[dict]:
    return _all_docs()


@pytest.fixture(scope="module")
def provider_configs(docs) -> list[dict]:
    return _by_kind(docs, "ProviderConfig")


@pytest.fixture(scope="module")
def composition(docs) -> dict:
    comps = _by_kind(docs, "Composition")
    assert comps, "expected a Composition manifest in the workspace"
    return comps[0]


def test_west_provider_config_added(provider_configs):
    west = [
        pc for pc in provider_configs
        if pc.get("spec", {}).get("region") == "us-west-2"
    ]
    assert west, (
        f"expected a ProviderConfig with spec.region: us-west-2, "
        f"found regions: {[pc.get('spec', {}).get('region') for pc in provider_configs]!r}"
    )
    names = {pc.get("metadata", {}).get("name") for pc in provider_configs}
    assert len(names) == len(provider_configs), (
        "ProviderConfig names must be distinct (the new one must not reuse the existing name)"
    )


def test_existing_east_resource_untouched(composition):
    resources = _pipeline_resources(composition)
    s3_bucket = [r for r in resources if r.get("name") == "s3-bucket"]
    assert s3_bucket, "expected the existing s3-bucket resource entry to still be present"
    base = s3_bucket[0].get("base", {})
    assert base.get("spec", {}).get("forProvider", {}).get("region") == "us-east-1", (
        "the existing s3-bucket resource's region must remain us-east-1"
    )
    assert base.get("spec", {}).get("providerConfigRef", {}).get("name") == "prod-us-east-1", (
        "the existing s3-bucket resource's providerConfigRef must remain prod-us-east-1"
    )


def test_new_resource_wired_to_west_provider(composition, provider_configs):
    west_names = {
        pc.get("metadata", {}).get("name")
        for pc in provider_configs
        if pc.get("spec", {}).get("region") == "us-west-2"
    }
    assert west_names, "no us-west-2 ProviderConfig found (see test_west_provider_config_added)"

    resources = _pipeline_resources(composition)
    new_resources = [r for r in resources if r.get("name") != "s3-bucket"]
    assert new_resources, "expected a new pipeline resource beyond the existing s3-bucket entry"

    wired = [
        r for r in new_resources
        if r.get("base", {}).get("spec", {}).get("providerConfigRef", {}).get("name") in west_names
    ]
    assert wired, (
        "expected the new resource's providerConfigRef to reference the new "
        f"us-west-2 ProviderConfig ({west_names!r}); got provider refs: "
        f"{[r.get('base', {}).get('spec', {}).get('providerConfigRef', {}).get('name') for r in new_resources]!r}"
    )


def test_claim_untouched(docs):
    claims = _by_kind(docs, "AWSWebService")
    if not claims:
        # The prompt only requires editing the composition/provider config;
        # an absent claim reproduction is not a failure.
        return
    claim = claims[0]
    assert claim.get("metadata", {}).get("name") == "myapp-prod", (
        "the existing claim's name must not change"
    )
    assert claim.get("spec", {}).get("bucket", {}).get("name") == "myapp-assets", (
        "the existing claim's spec must not change"
    )
