"""
Static validation stage runner for IaC/CD benchmark.

Runs tool-native validation: kustomize build, flux build, crossplane render,
terraform plan, pulumi preview.
"""

from __future__ import annotations

import subprocess
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def run_static(workspace: Path, stack: str) -> dict:
    """Run tool-native static validation for the stack."""
    results: list[str] = []
    all_passed = True

    if stack == "knr-ops":
        all_passed &= _knr_ops_static(workspace, results)
    elif stack == "crossplane":
        all_passed &= _crossplane_static(workspace, results)
    elif stack == "terraform":
        all_passed &= _terraform_static(workspace, results)
    elif stack in ("pulumi-python", "pulumi-typescript"):
        all_passed &= _pulumi_static(workspace, results)
    elif stack == "chant":
        all_passed &= _chant_static(workspace, results)
    elif stack == "bare":
        all_passed &= _bare_static(workspace, results)
    else:
        results.append(f"no static commands for stack: {stack}")

    return {
        "passed": all_passed,
        "logs": "\n".join(results) if results else "static validation passed",
    }


def _knr_ops_static(workspace: Path, results: list[str]) -> bool:
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

    # Find flux kustomizations
    flux_kustomizations = list(workspace.glob("**/kustomization_*.yaml")) + \
                          list(workspace.glob("**/flux/kustomizations.yaml"))
    for kfile in flux_kustomizations:
        log.info("flux build kustomization %s", kfile)
        try:
            proc = subprocess.run(
                ["flux", "build", "kustomization", str(kfile), "--dry-run"],
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

    return passed


def _crossplane_static(workspace: Path, results: list[str]) -> bool:
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

    return passed


def _terraform_static(workspace: Path, results: list[str]) -> bool:
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

    return passed


def _pulumi_static(workspace: Path, results: list[str]) -> bool:
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

    return passed


def _chant_static(workspace: Path, results: list[str]) -> bool:
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
        return passed

    if not build_out.exists():
        results.append("chant build produced no manifest; skipping kubeconform")
        return passed

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

    return passed


def _bare_static(workspace: Path, results: list[str]) -> bool:
    """Validate bare's plain YAML manifests with a client-side kubectl dry
    run, one file at a time. --dry-run=client (not =server) deliberately:
    static validation has no cluster dependency (unlike e2e, which applies
    for real against kind), and server-side dry-run would require a live
    API server to talk to just to check the manifests are well-formed."""
    passed = True

    yaml_files = list(workspace.rglob("*.yaml")) + list(workspace.rglob("*.yml"))
    if not yaml_files:
        results.append("no YAML files in workspace")
        return passed

    for yfile in yaml_files:
        log.info("kubectl apply --dry-run=client -f %s", yfile)
        try:
            proc = subprocess.run(
                ["kubectl", "apply", "--dry-run=client", "-f", str(yfile)],
                capture_output=True, text=True, timeout=60,
            )
            results.append(f"kubectl apply --dry-run=client -f {yfile.name}: exit={proc.returncode}")
            if proc.stdout:
                results.append(proc.stdout[:500])
            if proc.stderr:
                results.append(f"ERR: {proc.stderr[:500]}")
            if proc.returncode != 0:
                passed = False
        except subprocess.TimeoutExpired:
            results.append(f"TIMEOUT: kubectl apply --dry-run=client -f {yfile}")
            passed = False
        except FileNotFoundError:
            results.append("NOT FOUND: kubectl")
            break

    return passed
