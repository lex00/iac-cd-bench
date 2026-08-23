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
import re
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
# Code block extractor — writes model-generated code blocks as files
# ──────────────────────────────────────────────────────────────────────────

def extract_code_blocks(content: str, workspace: Path, stack: str = "knr-ops") -> list[Path]:
    """Extract fenced code blocks from model output and write them as files."""
    # Find all backticked file paths and fenced code blocks
    path_re = re.compile(r'`([^`\s]+(?:\.(yaml|yml|py|ts|tf|json|sh))[^`\s]*)`')
    block_re = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)

    path_matches = [(m.start(), m.group(1)) for m in path_re.finditer(content)]
    block_matches = [(m.start(), m.group(1), m.group(2).strip()) for m in block_re.finditer(content)]

    if not block_matches:
        return []

    # Only extract YAML/JSON/Python/TypeScript/HCL blocks (skip shell, text, markdown)
    extract_langs = {"yaml", "yml", "json", "python", "py", "typescript", "ts", "hcl", "terraform"}
    # For K8s stacks (knr-ops, crossplane), only extract manifests that look like K8s resources
    k8s_stacks = {"knr-ops", "crossplane"}
    # For terraform, only extract .tf files
    tf_stacks = {"terraform"}

    written: list[Path] = []
    used_blocks: set[int] = set()

    # Match each path with its nearest subsequent code block
    for path_pos, path_str in path_matches:
        # Skip dotfiles and non-standard extensions
        if path_str.startswith(".") or path_str.endswith(".gz"):
            continue

        for block_pos, lang, code in block_matches:
            if block_pos in used_blocks:
                continue
            # Only extract blocks with recognized language tags
            if lang not in extract_langs and lang not in ("", "yaml"):
                continue
            # For K8s stacks, skip non-K8s manifests (must have apiVersion)
            if stack in k8s_stacks and lang in ("yaml", "yml"):
                lines = [l for l in code.split("\n") if not l.strip().startswith("#")]
                clean_code = "\n".join(lines)
                if "apiVersion" not in clean_code:
                    continue
            # For terraform, skip non-HCL blocks
            if stack in tf_stacks and lang not in ("hcl", "terraform", ""):
                continue
            if block_pos > path_pos:
                dest = workspace / path_str
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(code + "\n")
                written.append(dest)
                used_blocks.add(block_pos)
                log.info("Wrote extracted file: %s (%d chars)", path_str, len(code))
                break

    # Write any remaining unused blocks with generic names (only recognized langs)
    for block_pos, lang, code in block_matches:
        if block_pos not in used_blocks:
            if lang not in extract_langs and lang not in ("", "yaml"):
                continue
            # For K8s stacks, skip non-K8s manifests
            if stack in k8s_stacks and lang in ("yaml", "yml"):
                clean_lines = [l for l in code.split("\n") if not l.strip().startswith("#")]
                if "apiVersion" not in "\n".join(clean_lines):
                    continue
            # For K8s stacks, don't write non-YAML files (also skip empty-lang blocks)
            if stack in k8s_stacks and lang not in ("yaml", "yml"):
                continue
            # For terraform, don't write non-HCL files
            if stack in tf_stacks and lang not in ("hcl", "terraform", ""):
                continue
            ext = {"yaml": ".yaml", "yml": ".yaml", "json": ".json", "python": ".py",
                   "py": ".py", "typescript": ".ts", "ts": ".ts", "hcl": ".tf",
                   "bash": ".sh", "sh": ".sh"}.get(lang, ".txt")
            name = f"generated_{len([p for p in written if str(p).endswith(ext)])}{ext}"
            dest = workspace / name
            dest.write_text(code + "\n")
            written.append(dest)

    return written


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

    def __init__(self, model: str, api_key: str, reasoning_effort: str | None = None):
        self.model = model
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
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

        messages: list[dict[str, Any]] = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                *extra_content,
            ],
        }]

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16384,
            "messages": messages,
        }

        # Opus 5.x and Opus 4.8 use adaptive thinking with output_config.effort
        # (4.8 rejects legacy budget_tokens with a 400 pointing at adaptive).
        # 900s read: max-effort 16k-token generations can exceed 600s non-streaming
        # (observed ReadTimeout loops on pulumi-typescript T3).
        if self.model.startswith("claude-opus-5") or self.model == "claude-opus-4-8":
            if self.reasoning_effort and self.reasoning_effort != "none":
                payload["thinking"] = {"type": "adaptive"}
                payload["output_config"] = {"effort": self.reasoning_effort}
                timeout = 900
            else:
                timeout = 120
        # Older models with extended thinking (opus 4.x, sonnet 4.x)
        elif self.reasoning_effort and self.reasoning_effort != "none" and (
            "opus-4" in self.model or "sonnet-4" in self.model
        ):
            payload["thinking"] = {"type": "enabled", "budget_tokens": 10240}
            timeout = 600
        else:
            timeout = 120

        import time
        resp = None
        last_exc: Exception | None = None
        for attempt in range(10):
            try:
                resp = httpx.post(
                    self._url,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                    timeout=timeout,
                )
                last_exc = None
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                log.warning("Anthropic transport error (%s), retrying", type(e).__name__)
                time.sleep(min(5 * 2 ** attempt + 10, 300))
                continue
            # Retry rate limits, overload, and transient 5xx
            if resp.status_code in (429, 529) or resp.status_code >= 500:
                wait = min(5 * 2 ** attempt + 10, 300)
                log.warning("Anthropic HTTP %s, retrying in %ds", resp.status_code, wait)
                time.sleep(wait)
                continue
            break
        if last_exc is not None:
            raise RuntimeError(f"Transport failure after 10 retries: {last_exc}")
        if resp is None or resp.status_code in (429, 529) or resp.status_code >= 500:
            raise RuntimeError(f"HTTP {resp.status_code if resp else 'none'} after 10 retries")
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

    def __init__(self, model: str, base_url: str, api_key: str = "«redacted:sk-…»", reasoning_effort: str | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        # Preserve the version segment (/v1 OpenAI-style, /v4 Zhipu/GLM-style);
        # default to /v1 when the base URL carries none.
        self._version = "/v1"
        for suffix in ("/v1", "/v2", "/v3", "/v4"):
            if self.base_url.endswith(suffix):
                self._version = suffix
                self.base_url = self.base_url[: -len(suffix)]
                break
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self._url = f"{self.base_url}{self._version}/chat/completions"

    @property
    def name(self) -> str:
        return self.model

    def complete(self, prompt: str, files: list[Path]) -> dict[str, Any]:
        import httpx

        # Append workspace files to the prompt (parity with AnthropicAdapter,
        # which sends them as extra content blocks).
        file_sections: list[str] = []
        for f in files:
            if f.is_file() and f.stat().st_size < 50000:
                try:
                    file_sections.append(f"File: {f.name}\n{f.read_text()}")
                except (UnicodeDecodeError, OSError):
                    continue
        full_prompt = prompt
        if file_sections:
            full_prompt = prompt + "\n\n### Workspace files\n\n" + "\n\n".join(file_sections)

        messages: list[dict[str, str]] = [{"role": "user", "content": full_prompt}]

        payload = {
            "model": self.model,
            "messages": messages,
        }
        # gpt-5+ models use max_completion_tokens instead of max_tokens
        if self.model.startswith("gpt-5"):
            payload["max_completion_tokens"] = 8192
        else:
            payload["max_tokens"] = 8192
        # gpt-5+ reasoning models reject temperature; kimi/qwen use reasoning_effort
        if "kimi" in self.model.lower() or "qwen" in self.model.lower():
            if self.reasoning_effort is not None:
                payload["reasoning_effort"] = self.reasoning_effort
            else:
                payload["reasoning_effort"] = "max"
            timeout = 600
        elif self.model.startswith("gpt-5"):
            # gpt-5+ models do not accept temperature
            if self.reasoning_effort and self.reasoning_effort != "none":
                payload["reasoning_effort"] = self.reasoning_effort
            timeout = 300
        elif "glm" in self.model.lower():
            # GLM reasoning burns the whole budget on long IaC outputs;
            # disable thinking unless explicitly requested. When an effort IS
            # requested, enable thinking and forward the level (GLM-5.3
            # supports low/high/max via reasoning_effort).
            payload["temperature"] = 0
            if self.reasoning_effort and self.reasoning_effort != "none":
                payload["thinking"] = {"type": "enabled"}
                payload["reasoning_effort"] = self.reasoning_effort
                payload["max_tokens"] = 32768  # room for thinking + answer
            else:
                payload["thinking"] = {"type": "disabled"}
            timeout = 600
        else:
            payload["temperature"] = 0
            timeout = 120

        import time
        resp = None
        last_exc: Exception | None = None
        for attempt in range(10):
            try:
                resp = httpx.post(
                    self._url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "content-type": "application/json",
                    },
                    json=payload,
                    timeout=timeout,
                )
                last_exc = None
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_exc = e
                log.warning("Transport error (%s), retrying", type(e).__name__)
                time.sleep(min(5 * 2 ** attempt + 10, 300))
                continue
            # Retry rate limits, transient 5xx, and request timeouts
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = min(5 * 2 ** attempt + 10, 300)
                log.warning("HTTP %s, retrying in %ds", resp.status_code, wait)
                time.sleep(wait)
                continue
            break
        if last_exc is not None:
            raise RuntimeError(f"Transport failure after 10 retries: {last_exc}")
        if resp is None or resp.status_code == 429 or resp.status_code >= 500:
            raise RuntimeError(f"HTTP {resp.status_code if resp else 'none'} after 10 retries")
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

    import time

    for run_idx in range(k):
        # Delay between runs to avoid rate limiting
        if run_idx > 0:
            log.info("Waiting 15s before run %d...", run_idx)
            time.sleep(15)
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

            # Extract code blocks from model output and write as files in workspace
            extracted = extract_code_blocks(completion["content"], workspace, stack)
            if extracted:
                result["extracted_files"] = [str(p) for p in extracted]

            # Stage 1: lint
            result["stages"]["lint"] = lint.run_lint(workspace, stack)

            # Stage 2: static
            result["stages"]["static"] = static.run_static(workspace, stack)

            # Stage 3: semantic (runs in the model's workspace)
            result["stages"]["semantic"] = semantic.run_semantic(task_dir, workspace)

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
    parser.add_argument("--reasoning-effort", default=None,
                        help="Reasoning effort for reasoning models (e.g. none, low, high, max)")
    parser.add_argument("--results-tag", default=None,
                        help="Suffix tag for the results directory (e.g. 'low' -> results/<model>-low/). "
                             "Prevents re-runs with different settings from overwriting prior runs.")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Parse stacks
    all_stacks = ["knr-ops", "crossplane", "terraform", "pulumi-python", "pulumi-typescript"]
    stacks = [args.stack] if args.stack else (all_stacks if args.stacks == "all" else args.stacks.split(","))

    # Build adapter
    base_url: str | None = args.base_url

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY") or "sk-placeholder"

    if args.model_provider == "anthropic":
        adapter: ModelAdapter = AnthropicAdapter(args.model, api_key,
                                                 reasoning_effort=args.reasoning_effort)
    else:
        adapter = OpenAICompatAdapter(args.model, base_url or "http://localhost:8000", api_key,
                                      reasoning_effort=args.reasoning_effort)

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

            # Delay between tasks to avoid rate limiting
            if task_dir != task_dirs[0]:
                log.info("Waiting 10s between tasks...")
                import time
                time.sleep(10)

            log.info("Running %s/%s (condition=%s)", stack, task_dir.name, args.condition)
            results = run_task(task_dir, adapter, args.k, args.e2e, args.condition)
            all_results.extend(results)

            # Write results
            model_name = adapter.name.replace("/", "-")
            if args.results_tag:
                model_name = f"{model_name}-{args.results_tag}"
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
