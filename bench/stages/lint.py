"""
Lint stage runner for IaC/CD benchmark.

Validates syntax, formatting, and basic correctness using stack-native linters.
"""

from __future__ import annotations

import subprocess
import logging
from pathlib import Path

log = logging.getLogger(__name__)

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
}


def run_lint(workspace: Path, stack: str) -> dict:
    """Run lint checks for the stack."""
    commands = LINT_COMMANDS.get(stack, [])
    if not commands:
        return {"passed": True, "logs": "no lint commands for stack"}

    results: list[str] = []
    all_passed = True

    # Find files for YAML stacks
    yaml_files = list(workspace.rglob("*.yaml")) + list(workspace.rglob("*.yml"))
    if stack in ("knr-ops", "crossplane"):
        files = [str(f) for f in yaml_files]
        # If no YAML files exist, lint passes (nothing to lint)
        if not files:
            return {"passed": True, "logs": "no YAML files in workspace"}
    elif stack in ("pulumi-typescript", "chant"):
        files = [str(f) for f in workspace.rglob("*.ts")]
        # If no TS files exist, lint passes (nothing to lint)
        if not files:
            return {"passed": True, "logs": "no TypeScript files in workspace"}
    else:
        files = ["."]

    for cmd, args, description in commands:
        if stack in ("knr-ops", "crossplane", "pulumi-typescript"):
            cmd_args: list[str] = [cmd] + args + files
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

    return {
        "passed": all_passed,
        "logs": "\n".join(results) if results else "lint passed",
    }
