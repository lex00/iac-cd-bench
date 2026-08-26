"""
Lint stage runner for IaC/CD benchmark.

Validates syntax, formatting, and basic correctness using stack-native linters.
"""

from __future__ import annotations

import subprocess
import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

# Vendored CRD JSON schemas (#83), mirrored from datreeio/CRDs-catalog at
# 7b1e26ef9deea49293714d204c1a2270aab1178f. Defined here rather than in
# bench.stages.static because static already imports this module; putting them
# the other way round would be a cycle.
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"
SCHEMA_TEMPLATE = "{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"


def kubeconform_schema_args() -> list[str]:
    """Point kubeconform at the vendored mirror, then its built-in registry."""
    return ["-schema-location", "default",
            "-schema-location", str(SCHEMA_DIR / SCHEMA_TEMPLATE)]


def is_k8s_manifest(path: Path) -> bool:
    """Does this YAML file contain at least one Kubernetes object?

    kubeconform is handed a file list, and a workspace legitimately contains
    YAML that is not a manifest — `.sops.yaml`, CI config, a Helm values file.
    Feeding those in fails the whole gate on `missing 'kind' key`, which is
    what the knr-ops golden did to its own lint stage. Judge a file by whether
    it declares apiVersion and kind, not by its extension.
    """
    try:
        docs = yaml.safe_load_all(path.read_text())
        return any(isinstance(d, dict) and "apiVersion" in d and "kind" in d
                   for d in docs)
    except (OSError, yaml.YAMLError):
        # Unreadable or unparseable: let kubeconform be the one to say so.
        return True

LINT_COMMANDS: dict[str, list[tuple[str, list[str], str]]] = {
    "knr-ops": [
        ("yq", ["eval", ".", "--"], "parse all YAML"),
        ("kubeconform", ["-summary", "-ignore-missing-schemas"], "validate CRDs"),
    ],
    "crossplane": [
        ("kubeconform", ["-summary", "-ignore-missing-schemas"], "validate CRDs"),
    ],
    "terraform": [
        ("terraform", ["init", "-backend=false", "-input=false"], "init"),
        ("terraform", ["validate"], "validate"),
    ],
    "pulumi-python": [
        (str(Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"),
         ["-m", "ruff", "check", "--select", "E,F", "."], "ruff check"),
    ],
    "pulumi-typescript": [
        ("tsc", ["--noEmit", "--skipLibCheck"], "tsc check"),
    ],
    "chant": [
        ("chant", ["lint", "."], "chant lint"),
        ("tsc", ["--noEmit", "--skipLibCheck"], "tsc check"),
    ],
    "bare": [
        ("yq", ["eval", ".", "--"], "parse all YAML"),
        ("kubeconform", ["-summary", "-ignore-missing-schemas"], "validate CRDs"),
    ],
}


def inapplicable(reason: str) -> dict:
    """A stage that had nothing to act on did not pass — it did not run.

    Recording `passed: True` for "no YAML files in workspace" is the
    vacuous-pass bug: the runs that produce no artifacts at all are exactly
    the most broken ones, and they collected free passes on lint and static
    while only semantic failed, inflating every gate rate in their favour.
    An inapplicable stage carries no `passed` key at all, so every existing
    `.get("passed", False)` reader treats it as not-passed, and
    bench.score.compute_score drops it from the correctness denominator
    rather than crediting it.
    """
    return {"inapplicable": True, "reason": reason, "logs": reason}


def run_lint(workspace: Path, stack: str) -> dict:
    """Run lint checks for the stack."""
    commands = LINT_COMMANDS.get(stack, [])
    if not commands:
        return inapplicable(f"no lint commands for stack: {stack}")

    results: list[str] = []
    all_passed = True

    # Find files for YAML stacks
    yaml_files = list(workspace.rglob("*.yaml")) + list(workspace.rglob("*.yml"))
    if stack in ("knr-ops", "crossplane", "bare"):
        files = [str(f) for f in yaml_files]
        if not files:
            return inapplicable("no YAML files in workspace")
    elif stack in ("pulumi-typescript", "chant"):
        files = [str(f) for f in workspace.rglob("*.ts")]
        if not files:
            return inapplicable("no TypeScript files in workspace")
    else:
        files = ["."]

    has_tsconfig = (workspace / "tsconfig.json").exists()

    for cmd, args, description in commands:
        if cmd == "tsc" and has_tsconfig:
            # A real tsconfig.json (e.g. golden-base/chant, which carries
            # "moduleResolution": "NodeNext" for @intentius/chant's
            # conditional-exports package.json) must be honored via -p;
            # invoking tsc on a bare file list uses tsc's classic-resolution
            # default and cannot resolve those imports, which would silently
            # look like a real type-check failure instead of an invocation
            # bug. Ephemeral task workspaces (no tsconfig.json copied into
            # seed/) fall through to the explicit-file-list invocation below,
            # unchanged.
            cmd_args: list[str] = [cmd, "-p", "tsconfig.json", "--noEmit"]
        elif cmd == "kubeconform":
            # Manifests only (#F6), and against the vendored schema mirror so
            # the CRDs these stacks are actually about get validated instead
            # of skipped (#F7): knr-ops lint on its own golden reported
            # `Valid: 3, Skipped: 23` before this.
            manifests = [f for f in files if is_k8s_manifest(Path(f))]
            if not manifests:
                results.append(f"[{description}] no Kubernetes manifests to validate")
                continue
            cmd_args = [cmd] + args + kubeconform_schema_args() + manifests
        elif stack in ("knr-ops", "crossplane", "pulumi-typescript", "bare"):
            cmd_args = [cmd] + args + files
        elif stack == "chant":
            # "chant lint ." already targets the workspace itself; only tsc
            # (which needs explicit inputs) gets the discovered .ts files.
            cmd_args = [cmd] + args + files if cmd == "tsc" else [cmd] + args
        else:
            cmd_args = [cmd] + args
        log.info("Running lint: %s (%s)", cmd, description)
        try:
            proc = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(workspace),
            )
            results.append(f"[{description}] {cmd}: exit={proc.returncode}")
            if proc.stdout:
                results.append(proc.stdout[:500])
            if proc.stderr:
                results.append(f"ERR: {proc.stderr[:500]}")
            if proc.returncode != 0:
                all_passed = False
        except subprocess.TimeoutExpired:
            results.append(f"TIMEOUT: {cmd} ({description})")
            all_passed = False
        except FileNotFoundError:
            results.append(f"NOT FOUND: {cmd} ({description})")
            log.warning("Command not found: %s", cmd)
            all_passed = False

    return {
        "passed": all_passed,
        "logs": "\n".join(results) if results else "lint passed",
    }
