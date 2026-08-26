"""
Static validation stage runner for IaC/CD benchmark.

Runs tool-native validation: kustomize build, flux build, crossplane render,
terraform plan, pulumi preview.
"""

from __future__ import annotations

import re
import subprocess
import logging
from pathlib import Path

import yaml

from bench.stages import lint as lint_mod

log = logging.getLogger(__name__)

# Vendored CRD JSON schemas (#83), mirrored from datreeio/CRDs-catalog at
# 7b1e26ef9deea49293714d204c1a2270aab1178f. Vendored rather than fetched at
# validation time so the gate stays offline and a run's verdict does not
# depend on a network round trip or on what upstream happened to hold that
# day. The layout matches the catalog's, so refreshing is a re-fetch.
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
SCHEMA_TEMPLATE = "{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"


def run_static(workspace: Path, stack: str) -> dict:
    """Run tool-native static validation for the stack.

    Each per-stack helper returns `(passed, acted)`. `acted` is False when the
    helper found nothing to build — no kustomization, no claim, no manifest —
    in which case the stage is recorded `inapplicable` rather than passed. See
    bench.stages.lint.inapplicable for why: a run that produced no artifacts
    used to collect a free static pass, which flattered exactly the runs that
    had failed hardest.
    """
    results: list[str] = []

    if stack == "knr-ops":
        all_passed, acted = _knr_ops_static(workspace, results)
    elif stack == "crossplane":
        all_passed, acted = _crossplane_static(workspace, results)
    elif stack == "terraform":
        all_passed, acted = _terraform_static(workspace, results)
    elif stack in ("pulumi-python", "pulumi-typescript"):
        all_passed, acted = _pulumi_static(workspace, results)
    elif stack == "chant":
        all_passed, acted = _chant_static(workspace, results)
    elif stack == "bare":
        all_passed, acted = _bare_static(workspace, results)
    else:
        return lint_mod.inapplicable(f"no static commands for stack: {stack}")

    if not acted:
        reason = "\n".join(results) or "nothing to build in workspace"
        return lint_mod.inapplicable(reason)

    return {
        "passed": all_passed,
        "logs": "\n".join(results) if results else "static validation passed",
    }


def _kubeconform_valid_count(summary: str) -> int:
    """How many resources kubeconform actually validated, from its summary.

    `Summary: N resources found in 1 file - Valid: 2, Invalid: 0, Errors: 0,
    Skipped: 3`. Skipped resources are ones whose schema was missing; they are
    not evidence of anything, so only the Valid count is returned.
    """
    m = re.search(r"Valid:\s*(\d+)", summary)
    return int(m.group(1)) if m else 0


def _flux_kustomization_target(kfile: Path, workspace: Path) -> tuple[str, Path]:
    """The (name, --path) a Flux Kustomization file should be built with.

    The name comes from the first Kustomization document's `metadata.name`,
    and the path from its `spec.path` resolved inside the workspace. Both fall
    back to something usable rather than raising: an unreadable or nameless
    file still gets built (and fails on its own merits) instead of taking the
    whole stage down with a parse error.
    """
    name = kfile.stem
    path = kfile.parent
    try:
        docs = [d for d in yaml.safe_load_all(kfile.read_text())
                if isinstance(d, dict)]
    except (OSError, yaml.YAMLError):
        return name, path

    for doc in docs:
        if doc.get("kind") != "Kustomization":
            continue
        name = (doc.get("metadata") or {}).get("name") or name
        spec_path = (doc.get("spec") or {}).get("path")
        if spec_path:
            candidate = (workspace / str(spec_path).lstrip("./")).resolve()
            if candidate.is_dir() and workspace.resolve() in candidate.parents:
                path = candidate
        break
    return name, path


def _knr_ops_static(workspace: Path, results: list[str]) -> tuple[bool, bool]:
    """Run kustomize build and flux build for knr-ops."""
    passed = True

    # Find kustomization.yaml files
    kustomizations = list(workspace.rglob("kustomization.yaml"))
    for kfile in kustomizations:
        overlay_dir = str(kfile.parent)
        log.info("kustomize build %s", overlay_dir)
        try:
            proc = subprocess.run(
                ["kustomize", "build", overlay_dir],
                capture_output=True, text=True, timeout=60,
            )
            results.append(f"kustomize build {overlay_dir}: exit={proc.returncode}")
            if proc.stderr:
                results.append(f"ERR: {proc.stderr[:500]}")
            if proc.returncode != 0:
                passed = False
        except subprocess.TimeoutExpired:
            results.append(f"TIMEOUT: kustomize build {overlay_dir}")
            passed = False
        except FileNotFoundError:
            results.append(f"NOT FOUND: kustomize")
            log.warning("Command not found: kustomize")
            passed = False

    # Find flux kustomizations
    flux_kustomizations = list(workspace.glob("**/kustomization_*.yaml")) + \
                          list(workspace.glob("**/flux/kustomizations.yaml"))
    for kfile in flux_kustomizations:
        log.info("flux build kustomization %s", kfile)
        try:
            # `flux build kustomization` takes a NAME, with the manifests
            # located by --path and the Kustomization itself by
            # --kustomization-file. Passing the file as the positional NAME
            # and omitting both flags (#82) left --path empty, so every call
            # exited 1 on `invalid resource path ""` before flux read a
            # manifest — the check could not pass, for any input, ever.
            name, path = _flux_kustomization_target(kfile, workspace)
            proc = subprocess.run(
                ["flux", "build", "kustomization", name,
                 "--path", str(path),
                 "--kustomization-file", str(kfile),
                 "--dry-run"],
                capture_output=True, text=True, timeout=60,
            )
            results.append(f"flux build {kfile.name}: exit={proc.returncode}")
            if proc.stderr:
                results.append(f"ERR: {proc.stderr[:500]}")
            if proc.returncode != 0:
                passed = False
        except subprocess.TimeoutExpired:
            results.append(f"TIMEOUT: flux build {kfile}")
            passed = False
        except FileNotFoundError:
            results.append(f"NOT FOUND: flux")
            log.warning("Command not found: flux")
            passed = False

    return passed, bool(kustomizations or flux_kustomizations)


def _crossplane_static(workspace: Path, results: list[str]) -> tuple[bool, bool]:
    """Run crossplane beta render for Crossplane."""
    passed = True

    # Find claims
    claims = list(workspace.rglob("*claim*.yaml"))
    compositions = list(workspace.rglob("*composition*.yaml"))
    xrds = list(workspace.rglob("*xrd*.yaml"))

    for claim in claims:
        log.info("crossplane render %s", claim)
        try:
            proc = subprocess.run(
                ["crossplane", "beta", "render", str(claim)],
                capture_output=True, text=True, timeout=60,
            )
            results.append(f"crossplane render {claim.name}: exit={proc.returncode}")
            if proc.stderr:
                results.append(f"ERR: {proc.stderr[:500]}")
            if proc.returncode != 0:
                passed = False
        except subprocess.TimeoutExpired:
            results.append(f"TIMEOUT: crossplane render {claim}")
            passed = False
        except FileNotFoundError:
            results.append(f"NOT FOUND: crossplane")
            log.warning("Command not found: crossplane")
            passed = False

    if not claims:
        results.append(
            "no crossplane claim (*claim*.yaml) in workspace: "
            f"{len(compositions)} composition(s), {len(xrds)} xrd(s) found, "
            "nothing to render"
        )

    return passed, bool(claims)


def _terraform_static(workspace: Path, results: list[str]) -> tuple[bool, bool]:
    """Run terraform validate and plan for Terraform."""
    passed = True

    # terraform validate
    log.info("terraform validate")
    try:
        proc = subprocess.run(
            ["terraform", "validate"],
            capture_output=True, text=True, timeout=60,
            cwd=str(workspace),
        )
        results.append(f"terraform validate: exit={proc.returncode}")
        if proc.stdout:
            results.append(proc.stdout[:500])
        if proc.returncode != 0:
            passed = False
    except subprocess.TimeoutExpired:
        results.append("TIMEOUT: terraform validate")
        passed = False
    except FileNotFoundError:
        results.append("NOT FOUND: terraform")
        log.warning("Command not found: terraform")
        passed = False

    return passed, True


def _pulumi_static(workspace: Path, results: list[str]) -> tuple[bool, bool]:
    """Run pulumi preview for Pulumi stacks."""
    passed = True

    log.info("pulumi preview")
    try:
        proc = subprocess.run(
            ["pulumi", "preview", "-s", "dev", "--non-interactive", "--diff"],
            capture_output=True, text=True, timeout=120,
            cwd=str(workspace),
        )
        results.append(f"pulumi preview: exit={proc.returncode}")
        if proc.stdout:
            results.append(proc.stdout[:2000])
        if proc.stderr:
            results.append(f"ERR: {proc.stderr[:500]}")
        if proc.returncode not in (0, 1):  # 1 = changes detected (still valid)
            passed = False
    except subprocess.TimeoutExpired:
        results.append("TIMEOUT: pulumi preview")
        passed = False
    except FileNotFoundError:
        results.append("NOT FOUND: pulumi")
        log.warning("Command not found: pulumi")
        passed = False

    return passed, True


def _chant_static(workspace: Path, results: list[str]) -> tuple[bool, bool]:
    """Build the chant workspace to YAML, then validate the emitted manifests
    with kubeconform (mirrors knr-ops's kubeconform usage)."""
    passed = True

    build_out = workspace / "build" / "manifests.yaml"

    log.info("chant build -f yaml")
    try:
        build_out.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["chant", "build", ".", "-f", "yaml", "-o", str(build_out)],
            capture_output=True, text=True, timeout=60,
            cwd=str(workspace),
        )
        results.append(f"chant build -f yaml: exit={proc.returncode}")
        if proc.stdout:
            results.append(proc.stdout[:500])
        if proc.stderr:
            results.append(f"ERR: {proc.stderr[:500]}")
        if proc.returncode != 0:
            passed = False
    except subprocess.TimeoutExpired:
        results.append("TIMEOUT: chant build -f yaml")
        passed = False
    except FileNotFoundError:
        results.append("NOT FOUND: chant")
        log.warning("Command not found: chant")
        return False, True

    if not build_out.exists():
        results.append("chant build produced no manifest; skipping kubeconform")
        return passed, True

    log.info("kubeconform %s", build_out)
    try:
        proc = subprocess.run(
            ["kubeconform", "-summary", "-ignore-missing-schemas", str(build_out)],
            capture_output=True, text=True, timeout=60,
        )
        results.append(f"kubeconform {build_out.name}: exit={proc.returncode}")
        if proc.stdout:
            results.append(proc.stdout[:500])
        if proc.stderr:
            results.append(f"ERR: {proc.stderr[:500]}")
        if proc.returncode != 0:
            passed = False
    except subprocess.TimeoutExpired:
        results.append(f"TIMEOUT: kubeconform {build_out}")
        passed = False
    except FileNotFoundError:
        results.append("NOT FOUND: kubeconform")
        log.warning("Command not found: kubeconform")
        passed = False

    return passed, True


def _bare_static(workspace: Path, results: list[str]) -> tuple[bool, bool]:
    """Validate bare's plain YAML manifests with a client-side kubectl dry
    run, one file at a time. --dry-run=client (not =server) deliberately:
    static validation has no cluster dependency (unlike e2e, which applies
    for real against kind), and server-side dry-run would require a live
    API server to talk to just to check the manifests are well-formed.

    That intent is not reachable with kubectl and never was (#81). Even with
    `--validate=false`, `kubectl apply --dry-run=client` contacts an API
    server to resolve API groups before it can map a kind to a resource, so
    with no cluster up every invocation died — first on `failed to download
    openapi`, then on `couldn't get current server API group list` — and the
    stage failed 100% of bare runs without judging a single manifest.

    kubeconform is used instead: schema-based, offline by construction, and
    already pinned in the toolchain. It runs stricter than lint runs it —
    lint omits `-strict`, this adds it — so the two stages stay distinct
    gates rather than one gate run twice.

    bare's tasks are ACK and Cluster API resources, whose CRD schemas
    kubeconform does not ship, so `schemas/` vendors them (#83) and
    `-schema-location` points at that mirror ahead of the built-in one. The
    versions are not a choice made here: they are the ones the task fixtures
    already use — ACK s3/iam/rds at v1alpha1, Cluster API at v1beta1.

    `-ignore-missing-schemas` is deliberately NOT passed. With the schemas
    vendored, a kind that still fails to resolve is a kind that does not
    exist, and that is a real defect worth failing: the v3 matrix has models
    emitting `UserPolicy`, `RolePolicyAttachment` and friends, none of which
    are ACK IAM kinds. Skipping them would score an invented resource as
    fine.
    """
    passed = True
    validated = 0

    yaml_files = list(workspace.rglob("*.yaml")) + list(workspace.rglob("*.yml"))
    if not yaml_files:
        results.append("no YAML files in workspace")
        return passed, False

    for yfile in yaml_files:
        log.info("kubeconform -strict %s", yfile)
        try:
            proc = subprocess.run(
                ["kubeconform", "-strict", "-summary",
                 "-schema-location", "default",
                 "-schema-location", str(SCHEMA_DIR / SCHEMA_TEMPLATE),
                 str(yfile)],
                capture_output=True, text=True, timeout=60,
            )
            results.append(f"kubeconform -strict {yfile.name}: exit={proc.returncode}")
            if proc.stdout:
                results.append(proc.stdout[:500])
                validated += _kubeconform_valid_count(proc.stdout)
            if proc.stderr:
                results.append(f"ERR: {proc.stderr[:500]}")
            if proc.returncode != 0:
                passed = False
        except subprocess.TimeoutExpired:
            results.append(f"TIMEOUT: kubeconform -strict {yfile}")
            passed = False
        except FileNotFoundError:
            results.append("NOT FOUND: kubeconform")
            log.warning("Command not found: kubeconform")
            passed = False
            break

    if passed and validated == 0:
        results.append(
            "no resource in the workspace resolved to a known schema — every "
            "kind was skipped, so nothing was validated (see #81)"
        )
        return passed, False

    return passed, True
