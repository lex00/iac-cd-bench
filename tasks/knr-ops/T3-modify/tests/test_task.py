"""Semantic grader for knr-ops T3-modify: add prod-only overlay patches.

knr-ops T3-modify ships no seed (the model synthesizes
overlays/prod/kustomization.yaml from the prompt's description of the base
repo -- the same "blind generate" idiom as knr-ops T2-generate), so there is
no seed file to diff against the way chant/bare T3 do. This grader instead
parses the emitted Kustomization's patches for the four requested prod-only
edits, and checks the dev overlay (if the model reproduced it at all) for
leakage of those same values -- the closest knr-ops equivalent of chant/
bare's seed-vs-edit diff.

Tolerant of both kustomize patch dialects the prompt allows: JSON6902 ops
(`patch: |` containing a `- op: replace / path: /spec/... / value: ...`
list) and strategic-merge (a partial resource, as a `patch:` mapping or a
`patch: |` block scalar) whose own apiVersion/kind/metadata.name imply the
target when `target:` is omitted. Values are read by walking the parsed
patch structure rather than regexing dumped YAML, since re-serializing a
multi-line block-scalar string through yaml.dump escapes its newlines and
breaks any regex that assumes them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


def _fenced_yaml_blocks(text: str) -> list[tuple[str | None, str]]:
    """(nearest preceding backticked path, code) for every yaml/bare-lang
    fenced block -- mirrors bench.runner.extract_code_blocks's own path/block
    pairing so this fallback sees what the runner would have extracted."""
    path_re = re.compile(r"`([^`\s]+\.ya?ml)`")
    block_re = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
    paths = [(m.start(), m.group(1)) for m in path_re.finditer(text)]
    out: list[tuple[str | None, str]] = []
    for m in block_re.finditer(text):
        lang, code = m.group(1), m.group(2).strip()
        if lang not in ("", "yaml", "yml"):
            continue
        nearest = None
        for pos, p in paths:
            if pos < m.start():
                nearest = p
            else:
                break
        out.append((nearest, code))
    return out


def _read_kustomization(env: str) -> str:
    """Real file first (extract_code_blocks writes it when the model
    backticks the path, since a Kustomization resource carries apiVersion);
    fall back to the raw completion's fenced blocks."""
    hits = [
        p for p in Path(".").rglob("kustomization.yaml")
        if env in [part.lower() for part in p.parts]
    ]
    for p in hits:
        try:
            return p.read_text()
        except Exception:
            continue

    out_path = Path("model_output.md")
    if not out_path.exists():
        return ""
    text = out_path.read_text()
    blocks = _fenced_yaml_blocks(text)

    named = [
        code for path, code in blocks
        if path and env in path.lower() and "kustomization" in path.lower()
    ]
    if named:
        return named[-1]

    # No backticked path at all -- fall back to a Kustomization resource
    # whose namePrefix matches the env (golden-base's own convention:
    # `namePrefix: dev-` / `namePrefix: prod-`).
    tagged = [
        code for _path, code in blocks
        if "kind: Kustomization" in code and re.search(rf"namePrefix:\s*{env}-", code)
    ]
    return tagged[-1] if tagged else ""


def _as_doc(text: str) -> dict:
    if not text:
        return {}
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return doc if isinstance(doc, dict) else {}


def _effective_target(entry: dict) -> tuple[str, str]:
    """kind/name for a patches: entry -- from its `target:` selector if
    present, else from the patch's own apiVersion/kind/metadata.name (valid
    for a strategic-merge patch, where kustomize infers the target)."""
    target = entry.get("target")
    if isinstance(target, dict) and (target.get("kind") or target.get("name")):
        return str(target.get("kind", "")), str(target.get("name", ""))
    parsed = _parsed_patch(entry)
    if isinstance(parsed, dict):
        return str(parsed.get("kind", "")), str((parsed.get("metadata") or {}).get("name", ""))
    return "", ""


def _parsed_patch(entry: dict):
    """entry['patch'] parsed into structured data: a list of JSON6902 ops,
    or a dict for a strategic-merge partial resource."""
    patch = entry.get("patch")
    if isinstance(patch, str):
        try:
            return yaml.safe_load(patch)
        except yaml.YAMLError:
            return None
    return patch


def _find_patch_entries(doc: dict, *, kind: str, name_substr: str, exclude: tuple[str, ...] = ()) -> list[dict]:
    entries: list[dict] = []
    for raw in (
        list(doc.get("patches") or [])
        + list(doc.get("patchesStrategicMerge") or [])
        + list(doc.get("patchesJson6902") or [])
    ):
        entry = {"patch": raw} if isinstance(raw, str) else raw if isinstance(raw, dict) else None
        if not entry:
            continue
        t_kind, t_name = _effective_target(entry)
        if t_kind.lower() != kind.lower():
            continue
        if name_substr not in t_name:
            continue
        if any(bad in t_name for bad in exclude):
            continue
        entries.append(entry)
    return entries


def _op_values(entry: dict, key: str) -> list:
    """Every value assigned to leaf `key`, across a JSON6902 op list (a
    `path` ending in `/key`) or a strategic-merge partial resource (`key`
    found anywhere via a deep walk of the parsed patch)."""
    parsed = _parsed_patch(entry)
    values: list = []
    if isinstance(parsed, list):
        for op in parsed:
            if isinstance(op, dict) and str(op.get("path", "")).rstrip("/").endswith(f"/{key}"):
                values.append(op.get("value"))
    elif isinstance(parsed, dict):
        stack = [parsed]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if key in node:
                    values.append(node[key])
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return values


def _patch_raw_text(entry: dict) -> str:
    """Human-readable text for loose 'did the patch mention X anywhere'
    checks. Uses the original block-scalar string directly when there is
    one (preserving its real newlines) rather than re-dumping through
    yaml.dump, which escapes them."""
    patch = entry.get("patch")
    if isinstance(patch, str):
        return patch
    if isinstance(patch, dict):
        return yaml.dump(patch, default_flow_style=False)
    return ""


@pytest.fixture(scope="module")
def prod_doc() -> dict:
    return _as_doc(_read_kustomization("prod"))


@pytest.fixture(scope="module")
def dev_doc() -> dict:
    return _as_doc(_read_kustomization("dev"))


def test_app_deployment_scaled(prod_doc):
    assert prod_doc, (
        "expected overlays/prod/kustomization.yaml (or an equivalent "
        "fenced block naming that path) in the model's output"
    )
    entries = _find_patch_entries(prod_doc, kind="Deployment", name_substr="myapp", exclude=("workers",))
    assert entries, "expected a kustomize patch targeting the myapp Deployment"
    values = [v for e in entries for v in _op_values(e, "replicas")]
    assert any(str(v) == "4" for v in values), f"expected replicas: 4, got: {values!r}"


def test_rds_instance_class_patched(prod_doc):
    assert prod_doc, "expected overlays/prod/kustomization.yaml in the model's output"
    entries = _find_patch_entries(prod_doc, kind="Instance", name_substr="db")
    assert entries, "expected a kustomize patch targeting the RDS Instance (myapp-dev-db)"
    values = [v for e in entries for v in _op_values(e, "instanceClass")]
    assert any(str(v).lower() == "db.t3.medium" for v in values), (
        f"expected instanceClass: db.t3.medium, got: {values!r}"
    )


def test_rds_multi_az_enabled(prod_doc):
    assert prod_doc, "expected overlays/prod/kustomization.yaml in the model's output"
    entries = _find_patch_entries(prod_doc, kind="Instance", name_substr="db")
    assert entries, "expected a kustomize patch targeting the RDS Instance (myapp-dev-db)"
    values = [v for e in entries for key in ("multiAz", "multiAZ", "multi_az") for v in _op_values(e, key)]
    assert any(v is True or str(v).lower() == "true" for v in values), (
        f"expected multi-AZ enabled (multiAz: true), got: {values!r}"
    )


def test_s3_cross_region_replication_added(prod_doc):
    assert prod_doc, "expected overlays/prod/kustomization.yaml in the model's output"
    entries = _find_patch_entries(prod_doc, kind="Bucket", name_substr="assets")
    assert entries, "expected a kustomize patch targeting the S3 Bucket (myapp-assets-dev)"
    combined_text = "\n".join(_patch_raw_text(e) for e in entries)
    assert "us-west-2" in combined_text, (
        f"expected a us-west-2 replication destination, got: {combined_text[:400]!r}"
    )
    assert re.search(r"replicat", combined_text, re.IGNORECASE), (
        "expected the patch to actually configure replication, not just mention the region"
    )


def test_dev_overlay_not_touched(dev_doc):
    """dev is optional in the answer at all (the prompt only requires
    editing prod), so an absent dev overlay is not a failure -- only a dev
    overlay that leaked prod-only values is."""
    if not dev_doc:
        return
    entries = _find_patch_entries(dev_doc, kind="Bucket", name_substr="assets")
    combined_text = "\n".join(_patch_raw_text(e) for e in entries)
    assert "us-west-2" not in combined_text, "dev overlay must not pick up prod's S3 replication"

    rds_entries = _find_patch_entries(dev_doc, kind="Instance", name_substr="db")
    rds_values = [v for e in rds_entries for v in _op_values(e, "instanceClass")]
    assert not any(str(v).lower() == "db.t3.medium" for v in rds_values), (
        "dev overlay must not pick up prod's RDS instance class change"
    )

    deploy_entries = _find_patch_entries(dev_doc, kind="Deployment", name_substr="myapp", exclude=("workers",))
    deploy_values = [v for e in deploy_entries for v in _op_values(e, "replicas")]
    assert not any(str(v) == "4" for v in deploy_values), (
        "dev overlay must not scale the app deployment to 4 replicas"
    )
