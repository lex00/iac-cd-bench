"""
IaC/CD Understanding Benchmark Runner

Materializes a task workspace, invokes a model adapter, runs validation stages,
and writes scored results.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from bench.stages import lint, static, semantic, e2e

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"
RESULTS_DIR = ROOT / "results"

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# Task materializer
# ──────────────────────────────────────────────────────────────────────────

def materialize_task(task_dir: Path, workspace: Path, condition: str = "warm") -> dict[str, Any]:
    """Copy seed into workspace, optionally inject docs for warm condition."""
    import yaml

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

        extra_content: list[dict[str, str]] = []
        for f in files:
            if f.is_file() and f.stat().st_size < 50000:
                extra_content.append({
                    "type": "text",
                    "text": f"File: {f.name}\n{f.read_text()}",
                })

        messages: list[dict[str, Any]] = [{"role": "user", "content": [
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
        if not resp.is_success:
            log.error("Anthropic API error %s: %s", resp.status_code, resp.text[:1000])
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
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

    def __init__(self, model: str, base_url: str, api_key: str = "«redacted:sk-…»"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        # Strip /v1 suffix if present to avoid double /v1 paths
        if self.base_url.endswith("/v1"):
            self.base_url = self.base_url[:-3]
        self.api_key = api_key
        self._url = f"{self.base_url}/v1/chat/completions"

    @property
    def name(self) -> str:
        return self.model

    def complete(self, prompt: str, files: list[Path]) -> dict[str, Any]:
        import httpx

        messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]

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
        data: dict[str, Any] = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning") or ""
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
    spec_path = task_dir / "spec.yaml"
    import yaml
    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    stack = spec["stack"]
    task_id = spec.get("id", task_dir.name)

    results: list[dict[str, Any]] = []

    for run_idx in range(k):
        # Create fresh workspace
        workspace = Path(tempfile.mkdtemp(prefix=f"bench-{stack}-"))
        log.info("Run %d: workspace %s", run_idx, workspace)

        # Materialize task
        task_info = materialize_task(task_dir, workspace, condition)
        prompt = task_info["prompt"]

        # Discover files in workspace
        workspace_files: list[Path] = []
        for f in sorted(workspace.rglob("*")):
            if f.is_file() and not f.name.startswith("."):
                workspace_files.append(f)

        result: dict[str, Any] = {
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
            output_file = workspace / "model_output.md"
            output_file.write_text(completion["content"])
            result["content"] = completion["content"]

            # Stage 1: lint
            result["stages"]["lint"] = lint.run_lint(workspace, stack)

            # Stage 2: static
            result["stages"]["static"] = static.run_static(workspace, stack)

            # Stage 3: semantic
            result["stages"]["semantic"] = semantic.run_semantic(task_dir)

            # Stage 4: e2e (gated)
            if run_e2e:
                result["stages"]["e2e"] = e2e.run_e2e(workspace, stack)

        except Exception as e:
            result["error"] = str(e)
            result["stages"]["lint"] = {"passed": False, "logs": str(e)}

        results.append(result)

        # Clean workspace between runs
        shutil.rmtree(workspace, ignore_errors=True)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="IaC/CD Benchmark Runner")
    parser.add_argument("--model", required=True, help="Model identifier")
    parser.add_argument("--model-provider", default="anthropic", choices=["anthropic", "openai-compat"])
    parser.add_argument("--base-url", default=None, help="Base URL for OpenAI-compatible endpoints")
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
    base_url: str | None = args.base_url

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY") or "sk-placeholder"

    if args.model_provider == "anthropic":
        adapter: ModelAdapter = AnthropicAdapter(args.model, api_key)
    else:
        adapter = OpenAICompatAdapter(args.model, base_url or "http://localhost:8000", api_key)

    # Discover tasks
    all_results: list[dict[str, Any]] = []
    for stack in stacks:
        stack_dir = TASKS_DIR / stack
        if not stack_dir.exists():
            log.warning("Stack dir not found: %s", stack_dir)
            continue

        task_dirs = sorted(d for d in stack_dir.iterdir() if d.is_dir())

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
            result_dir = RESULTS_DIR / model_name / stack / args.condition
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
