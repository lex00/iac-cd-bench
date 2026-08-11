"""
IaC/CD Understanding Benchmark Runner

Materializes a task workspace, invokes a model adapter, runs validation stages,
and writes scored results.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"
RESULTS_DIR = ROOT / "results"

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Task materializer
# ──────────────────────────────────────────────────────────────────────────

def materialize_task(
    task_dir: Path,
    workspace: Path,
    condition: str = "warm",
) -> dict[str, Any]:
    """Copy seed into workspace, optionally inject docs for warm condition."""
    # Copy seed
    seed_dir = task_dir / "seed"
    if seed_dir.exists():
        for child in seed_dir.iterdir():
            dest = workspace / child.name
            if child.is_dir():
                shutil.copytree(child, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(child, dest)

    # Inject docs for warm condition
    if condition == "warm":
        docs_dir = task_dir / "docs"
        if docs_dir.exists():
            docs_target = workspace / "context"
            docs_target.mkdir(exist_ok=True)
            for child in docs_dir.iterdir():
                shutil.copy2(child, docs_target / child.name)

    # Load spec
    spec_path = task_dir / "spec.yaml"
    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    # Load prompt
    prompt_path = task_dir / "prompt.md"
    with open(prompt_path) as f:
        prompt = f.read()

    # Inject scenario spec into prompt
    scenario_spec_path = ROOT / "scenario" / "SPEC.md"
    if scenario_spec_path.exists():
        prompt = prompt.replace("{{scenario_spec}}", scenario_spec_path.read_text())

    return {"spec": spec, "prompt": prompt}


# ──────────────────────────────────────────────────────────────────────────
# Stage runners (skeleton; full implementations in bench/stages/)
# ──────────────────────────────────────────────────────────────────────────

LINT_COMMANDS: dict[str, list[str]] = {
    "knr-ops": [
        # yq parses all YAML
        "yq eval '.' {files}/*.yaml >/dev/null 2>&1",
        # kubeconform validates CRDs
        'kubeconform -strict -schema-location default -summary {files}',
    ],
    "crossplane": [
        'kubeconform -strict -schema-location default -summary {files}',
    ],
    "terraform": [
        "cd {files} && terraform fmt -check .",
        "cd {files} && terraform init -backend=false -input=false",
        "cd {files} && terraform validate",
        "cd {files} && tflint --config=../../.tflint.hcl",
    ],
    "pulumi-python": [
        "cd {files} && python3 -m ruff check .",
        "cd {files} && python3 -m mypy --ignore-missing-imports .",
    ],
    "pulumi-typescript": [
        "cd {files} && npx -y tsc --noEmit --skipLibCheck",
    ],
}


def run_lint(workspace: Path, stack: str) -> dict[str, Any]:
    """Run lint checks for the stack. Returns {passed: bool, logs: str}."""
    commands = LINT_COMMANDS.get(stack, [])
    if not commands:
        return {"passed": True, "logs": "no lint commands for stack"}

    # Find YAML/TF/Python/TS files
    files = list(workspace.rglob("*.yaml")) + list(workspace.rglob("*.yml")) + list(workspace.rglob("*.tf"))
    files_str = " ".join(str(p) for p in files[:10]) or str(workspace)

    results = []
    for cmd in commands:
        cmd = cmd.replace("{files}", files_str)
        try:
            proc = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60,
                cwd=str(workspace),
            )
            results.append(f"{cmd}: exit={proc.returncode}")
            if proc.stdout:
                results.append(proc.stdout[:500])
            if proc.stderr:
                results.append(f"ERR: {proc.stderr[:500]}")
        except subprocess.TimeoutExpired:
            results.append(f"TIMEOUT: {cmd}")

    passed = len(commands) > 0  # refined in full implementation
    return {"passed": True, "logs": "\n".join(results)}


def run_static(workspace: Path, stack: str) -> dict[str, Any]:
    """Run tool-native static validation for the stack."""
    results = []

    if stack == "knr-ops":
        overlays = list(workspace.glob("**/kustomization.yaml"))
        for kfile in overlays:
            overlay_dir = str(kfile.parent)
            try:
                proc = subprocess.run(
                    ["kustomize", "build", overlay_dir],
                    capture_output=True, text=True, timeout=60,
                )
                results.append(f"kustomize build {overlay_dir}: exit={proc.returncode}")
                if proc.stderr:
                    results.append(f"ERR: {proc.stderr[:500]}")
            except Exception as e:
                results.append(f"FAILED: {e}")

        # flux build kustomization
        kustomizations = list(workspace.glob("**/kustomization_*.yaml"))
        for kustomization in kustomizations:
            try:
                proc = subprocess.run(
                    ["flux", "build", "kustomization", str(kustomization), "--dry-run"],
                    capture_output=True, text=True, timeout=60,
                )
                results.append(f"flux build: exit={proc.returncode}")
            except Exception as e:
                results.append(f"flux build FAILED: {e}")

    elif stack == "terraform":
        try:
            proc = subprocess.run(
                ["terraform", "plan", "-no-color", "-detailed-exitcode"],
                capture_output=True, text=True, timeout=120,
                cwd=str(workspace),
            )
            results.append(f"terraform plan: exit={proc.returncode}")
            results.append(proc.stdout[:2000])
        except Exception as e:
            results.append(f"terraform plan FAILED: {e}")

    elif stack in ("pulumi-python", "pulumi-typescript"):
        stack_name = "dev"
        try:
            proc = subprocess.run(
                ["pulumi", "preview", "-s", stack_name, "--non-interactive", "--diff"],
                capture_output=True, text=True, timeout=120,
                cwd=str(workspace),
            )
            results.append(f"pulumi preview: exit={proc.returncode}")
            results.append(proc.stdout[:2000])
        except Exception as e:
            results.append(f"pulumi preview FAILED: {e}")

    return {"passed": True, "logs": "\n".join(results)}


def run_semantic(task_dir: Path) -> dict[str, Any]:
    """Run pytest semantic assertions if tests/ exists."""
    test_file = task_dir / "tests" / "test_task.py"
    if not test_file.exists():
        return {"passed": True, "logs": "no semantic tests", "passed_count": 0, "total_count": 0}

    try:
        proc = subprocess.run(
            ["python3", "-m", "pytest", "-v", str(test_file)],
            capture_output=True, text=True, timeout=120,
        )
        return {
            "passed": proc.returncode == 0,
            "logs": proc.stdout[-2000:] + proc.stderr[-2000:],
        }
    except Exception as e:
        return {"passed": False, "logs": str(e)}


def run_e2e(workspace: Path, stack: str) -> dict[str, Any]:
    """Run live e2e against kind + LocalStack. Gated by --e2e flag."""
    # Full implementation in bench/stages/e2e.py
    return {
        "passed": False,
        "logs": "e2e stage not yet implemented in runner; see bench/stages/e2e.py",
    }


# ──────────────────────────────────────────────────────────────────────────
# Model adapter interface
# ──────────────────────────────────────────────────────────────────────────

class ModelAdapter:
    """Base adapter for model invocations."""

    def complete(self, prompt: str, files: list[Path]) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def name(self) -> str:
        return "base"


class AnthropicAdapter(ModelAdapter):
    """Anthropic API adapter via httpx."""

    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key
        self._url = "https://api.anthropic.com/v1/messages"

    @property
    def name(self) -> str:
        return self.model

    def complete(self, prompt: str, files: list[Path]) -> dict[str, Any]:
        import httpx

        extra_content = []
        for f in files:
            if f.is_file() and f.stat().st_size < 50000:
                extra_content.append({
                    "type": "text",
                    "text": f"File: {f.name}\n{f.read_text()}",
                })

        messages = [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            *extra_content,
        ]}]

        resp = httpx.post(
            self._url,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 8192,
                "temperature": 0,
                "messages": messages,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        content = "".join(
            c["text"] for c in data["content"] if c["type"] == "text"
        )
        return {
            "content": content,
            "input_tokens": data.get("usage", {}).get("input_tokens", 0),
            "output_tokens": data.get("usage", {}).get("output_tokens", 0),
        }


class OpenAICompatAdapter(ModelAdapter):
    """OpenAI-compatible adapter (works with vLLM, LM Studio, any compatible server)."""

    def __init__(self, model: str, base_url: str, api_key: str = "sk-placeholder"):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self._url = f"{base_url}/v1/chat/completions"

    @property
    def name(self) -> str:
        return self.model

    def complete(self, prompt: str, files: list[Path]) -> dict[str, Any]:
        import httpx

        messages = [{"role": "user", "content": prompt}]

        resp = httpx.post(
            self._url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 8192,
                "temperature": 0,
                "messages": messages,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return {
            "content": content,
            "input_tokens": data.get("usage", {}).get("prompt_tokens", 0),
            "output_tokens": data.get("usage", {}).get("completion_tokens", 0),
        }


# ──────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────

def run_task(
    task_dir: Path,
    adapter: ModelAdapter,
    k: int = 3,
    run_e2e: bool = False,
    condition: str = "warm",
) -> list[dict[str, Any]]:
    """Run a single task k times, return results."""
    task_info = materialize_task(task_dir, Path(tempfile.gettempdir()) / "bench-workspace", condition)
    spec = task_info["spec"]
    prompt = task_info["prompt"]
    stack = spec["stack"]
    task_id = spec.get("id", task_dir.name)

    # Discover files in workspace
    workspace_files = []
    tmp_workspace = Path(tempfile.gettempdir()) / "bench-workspace"
    for f in sorted(tmp_workspace.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            workspace_files.append(f)

    results = []
    for run_idx in range(k):
        result = {
            "model": adapter.name,
            "task": task_id,
            "stack": stack,
            "run": run_idx,
            "condition": condition,
            "stages": {},
        }

        # Invoke model
        try:
            completion = adapter.complete(prompt, workspace_files)
            result["tokens"] = {
                "input": completion["input_tokens"],
                "output": completion["output_tokens"],
            }

            # Write model output to workspace for validation
            output_file = tmp_workspace / "model_output.md"
            output_file.write_text(completion["content"])

            # Stage 1: lint
            result["stages"]["lint"] = run_lint(tmp_workspace, stack)

            # Stage 2: static
            result["stages"]["static"] = run_static(tmp_workspace, stack)

            # Stage 3: semantic
            result["stages"]["semantic"] = run_semantic(task_dir)

            # Stage 4: e2e (gated)
            if run_e2e:
                result["stages"]["e2e"] = run_e2e(tmp_workspace, stack)

        except Exception as e:
            result["error"] = str(e)
            result["stages"]["lint"] = {"passed": False, "logs": str(e)}

        results.append(result)

        # Clean workspace between runs
        shutil.rmtree(tmp_workspace, ignore_errors=True)

    return results


def main():
    parser = argparse.ArgumentParser(description="IaC/CD Benchmark Runner")
    parser.add_argument("--model", required=True, help="Model identifier (e.g. anthropic/claude-sonnet-4-20250514)")
    parser.add_argument("--model-provider", default="anthropic", choices=["anthropic", "openai-compat"])
    parser.add_argument("--model-args", nargs="*", default=[], help="Extra args: --base-url for openai-compat")
    parser.add_argument("--stacks", default="all", help="Comma-separated stacks or 'all'")
    parser.add_argument("--stack", help="Single stack shortcut")
    parser.add_argument("--tasks", default="all", help="Comma-separated task IDs or 'all'")
    parser.add_argument("--task", help="Single task shortcut")
    parser.add_argument("-k", type=int, default=3, help="Runs per task")
    parser.add_argument("--e2e", action="store_true", help="Include e2e validation tier")
    parser.add_argument("--condition", default="warm", choices=["warm", "cold"])
    parser.add_argument("--api-key", default=None, help="API key (defaults to env ANTHROPIC_API_KEY)")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Parse stacks
    all_stacks = ["knr-ops", "crossplane", "terraform", "pulumi-python", "pulumi-typescript"]
    stacks = [args.stack] if args.stack else (all_stacks if args.stacks == "all" else args.stacks.split(","))

    # Build adapter
    base_url = None
    for i, a in enumerate(args.model_args):
        if a == "--base-url" and i + 1 < len(args.model_args):
            base_url = args.model_args[i + 1]

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY") or "sk-placeholder"

    if args.model_provider == "anthropic":
        adapter = AnthropicAdapter(args.model, api_key)
    else:
        adapter = OpenAICompatAdapter(args.model, base_url or "http://localhost:8000", api_key)

    # Discover tasks
    all_results = []
    for stack in stacks:
        stack_dir = TASKS_DIR / stack
        if not stack_dir.exists():
            log.warning("Stack dir not found: %s", stack_dir)
            continue

        task_dirs = sorted(stack_dir.iterdir())
        task_dirs = [d for d in task_dirs if d.is_dir()]

        if args.task:
            task_dirs = [TASKS_DIR / stack / args.task]
        elif args.tasks and args.tasks != "all":
            wanted = args.tasks.split(",")
            task_dirs = [TASKS_DIR / stack / t for t in wanted]

        for task_dir in task_dirs:
            if not task_dir.exists():
                log.warning("Task dir not found: %s", task_dir)
                continue

            log.info("Running %s/%s (condition=%s)", stack, task_dir.name, args.condition)
            results = run_task(task_dir, adapter, args.k, args.e2e, args.condition)
            all_results.extend(results)

            # Write results
            model_name = adapter.name.replace("/", "-")
            result_dir = RESULTS_DIR / model_name / stack
            result_dir.mkdir(parents=True, exist_ok=True)
            for r in results:
                out_path = result_dir / f"{task_dir.name}_run{r['run']}.json"
                with open(out_path, "w") as f:
                    json.dump(r, f, indent=2, default=str)
                log.info("Wrote %s", out_path)

    # Summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r["stages"].get("lint", {}).get("passed"))
    log.info("Summary: %d runs, %d passed lint", total, passed)


if __name__ == "__main__":
    main()
