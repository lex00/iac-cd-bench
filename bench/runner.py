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

from bench import judge as judge_mod
from bench import preflight as preflight_mod
from bench import provenance as prov_mod
from bench import validity as validity_mod
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
    # For K8s stacks (knr-ops, crossplane, bare), only extract manifests that look like K8s resources
    k8s_stacks = {"knr-ops", "crossplane", "bare"}
    # For terraform, only extract .tf files
    tf_stacks = {"terraform"}
    # For chant, the model writes TypeScript source (not the YAML the stack
    # emits); only extract .ts blocks so lint/static/e2e build the source and
    # gate on the YAML chant emits, rather than misdetecting the model's
    # commentary/example-output blocks as the artifact to validate.
    chant_stacks = {"chant"}

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
            # For chant, skip anything that isn't TypeScript source
            if stack in chant_stacks and lang not in ("typescript", "ts", ""):
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
            # For chant, don't write non-TypeScript files
            if stack in chant_stacks and lang not in ("typescript", "ts", ""):
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

def _bootstrap_chant_workspace(workspace: Path) -> None:
    """Symlink the shared golden-base/chant node_modules template into a
    materialized chant workspace, and copy tsconfig.json + package.json
    from the same template.

    tsc/chant need node_modules to resolve @intentius/chant's conditional
    package exports (see lint.py), and tsc's NodeNext resolution needs a
    tsconfig.json (-p tsconfig.json, per lint.py) plus a package.json
    declaring "type": "module" (the nearest package.json is how Node/tsc
    decide whether the workspace's `.js`-suffixed relative imports of `.ts`
    sources are ESM). Symlinking node_modules (rather than copying it)
    is what makes a 36+-run chant matrix share one install instead of
    npm-installing per run; see bench.stages.e2e.ensure_chant_node_modules
    for where that one shared install happens.

    Every file this writes is skipped if the workspace already has one
    (e.g. a future task seed shipping its own), so this never clobbers
    seed content.
    """
    golden_dir = e2e.ensure_chant_node_modules()

    node_modules_link = workspace / "node_modules"
    if not node_modules_link.exists():
        node_modules_link.symlink_to(golden_dir / "node_modules", target_is_directory=True)

    for name in ("tsconfig.json", "package.json"):
        dest = workspace / name
        if not dest.exists():
            shutil.copy2(golden_dir / name, dest)


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

    # chant tasks whose spec actually runs a toolchain stage (lint/static/
    # e2e) need node_modules + tsconfig.json bootstrapped into the
    # workspace (issue #58); pure rubric/prediction chant tasks (all three
    # disabled) skip this so their workspace and grader never see a
    # node_modules tree at all.
    if spec.get("stack") == "chant" and any(
        _stage_enabled(spec, name) for name in ("lint", "static", "e2e")
    ):
        _bootstrap_chant_workspace(workspace)

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

    def __init__(self, model: str, api_key: str, reasoning_effort: str | None = None,
                 temperature: float | None = None):
        self.model = model
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        # Only set for deterministic side-calls (the rubric judge). Left None
        # for benchmark runs: the 4.7+/5 family rejects sampling parameters.
        self.temperature = temperature
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
        if self.temperature is not None:
            payload["temperature"] = self.temperature

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


class ClaudeCliAdapter(ModelAdapter):
    """Adapter that shells out to the `claude` CLI in non-interactive print mode.

    Used when no Anthropic API key is available and the harness instead runs
    against the machine's existing Claude Code authentication (OAuth via
    `claude.ai` login, or `CLAUDE_CODE_OAUTH_TOKEN`) - the same mechanism
    chant-bench uses to invoke `claude` for its own trials (chant-bench's
    vendored aws-bench fork shells out to
    `claude --output-format=stream-json --print`, model pinned via
    `ANTHROPIC_MODEL`; here the model is pinned via the equivalent `--model`
    flag and reasoning effort via `--effort`, both confirmed present in
    `claude --help` on this machine).

    One-shot only: tools are disabled (`--tools ""`) and settings/CLAUDE.md
    discovery is disabled (`--setting-sources ""`), so this stays a pure
    prompt -> completion call with the same result shape as AnthropicAdapter
    / OpenAICompatAdapter, rather than an agentic loop that edits the
    workspace or picks up unrelated project/user instructions itself.

    #59: `--tools ""` alone does NOT stop the model from behaving like an
    agent. The *default* Claude Code system prompt still frames the session
    as an agentic coding tool, so even with zero tools wired up, models
    reliably reach for that framing - narrating an intent to explore the
    workspace ("I'll look for the actual diff artifacts...", followed by a
    rendered fenced **Bash** block that is never executed) or stalling out
    asking for files/tool access instead of answering from the prompt they
    were given. Since `--print` returns only the first assistant turn as
    `result`, that preamble (or clarifying question) *is* the run's entire
    recorded output - typically under the ~600-1500 char range real answers
    fall in. This was measured directly: on knr-ops T5-review (opus/haiku,
    the rubric shape that triggered it most), the stock command produced a
    short stub or tool-narration preamble in 2 of 3 live probes; every trial
    was a substantive full-length answer once `--system-prompt` fully
    replaced the default agentic framing (see PR body / issue #59 for the
    probe transcripts). `--append-system-prompt` (which layers on top of,
    rather than replacing, the default prompt) also improved things in a
    single trial but was not the one taken to 5-for-5 - `--system-prompt` is
    the one actually shipped here, both for that stronger empirical run and
    because it removes the agentic framing at the root instead of trying to
    talk the model out of it.

    Token usage, when reported, comes from the CLI's own `usage` block, which
    reflects Claude Code's internal system prompt and prompt-caching
    accounting - it is not directly comparable to the raw `input_tokens` the
    Anthropic API adapter reports for a bare `messages.create` call.
    """

    # Replaces Claude Code's default (agentic-coding-tool) system prompt
    # outright. `--append-system-prompt` layers new text on *top of* that
    # default framing and left the model reaching for tool-shaped narration
    # in live probes; a full `--system-prompt` override removed the framing
    # that causes the reach in the first place. See class docstring (#59).
    SINGLE_TURN_SYSTEM_PROMPT = (
        "You are being invoked as a one-shot text completion API, not as an "
        "interactive coding agent. You have no tools, no filesystem access, "
        "and no ability to run commands - none are attached to this "
        "session. Never describe, narrate, or propose using a tool (Bash, "
        "Read, grep, find, ls, etc.); there are none, and doing so wastes "
        "the turn. Answer the request directly and completely in prose, "
        "using only the information contained in this message."
    )

    def __init__(self, model: str, reasoning_effort: str | None = None,
                 claude_bin: str | None = None, timeout: int = 600):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.claude_bin = claude_bin or os.environ.get("BENCH_CLAUDE_BIN", "claude")
        self.timeout = timeout

    @property
    def name(self) -> str:
        return self.model

    def _build_command(self) -> list[str]:
        cmd = [
            self.claude_bin,
            "--print",
            "--output-format", "json",
            "--model", self.model,
            "--permission-mode", "bypassPermissions",
            "--no-session-persistence",
            "--tools", "",
            "--setting-sources", "",
            "--system-prompt", self.SINGLE_TURN_SYSTEM_PROMPT,
        ]
        # `--effort` is a real, documented pin (`claude --help`): low, medium,
        # high, xhigh, max. Recorded on self.reasoning_effort either way, so
        # run_task can stamp the run JSON with what was actually pinned
        # rather than defaulting silently.
        if self.reasoning_effort and self.reasoning_effort != "none":
            cmd += ["--effort", self.reasoning_effort]
        return cmd

    def complete(self, prompt: str, files: list[Path]) -> dict[str, Any]:
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

        cmd = self._build_command()
        try:
            proc = subprocess.run(
                cmd, input=full_prompt, capture_output=True, text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"claude CLI timed out after {self.timeout}s") from e
        except FileNotFoundError as e:
            raise RuntimeError(
                f"claude CLI binary '{self.claude_bin}' not found on PATH"
            ) from e

        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}: {(proc.stderr or '')[-2000:]}"
            )

        try:
            data: dict[str, Any] = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"claude CLI did not return valid JSON on stdout: {proc.stdout[-500:]!r}"
            ) from e

        if data.get("is_error"):
            raise RuntimeError(f"claude CLI reported an error result: {data}")

        usage = data.get("usage") or {}
        return {
            "content": data.get("result", ""),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cost_usd": data.get("total_cost_usd"),
            "session_id": data.get("session_id"),
        }


# ──────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────

def _stage_enabled(spec: dict[str, Any], name: str) -> bool:
    """Whether spec.yaml enables a validation stage (stages.<name>.enabled).

    Defaults to True when the spec has no `stages:` block, or omits a given
    stage's `enabled` key — matching pre-gating behavior, where every task
    ran every stage unconditionally. Every task's spec.yaml in this repo
    declares `stages:` explicitly, so the default only matters for specs
    that don't (future tasks, or malformed ones)."""
    stages_spec = spec.get("stages") or {}
    stage_spec = stages_spec.get(name) or {}
    return bool(stage_spec.get("enabled", True))


def run_task(
    task_dir: Path,
    adapter: ModelAdapter,
    k: int = 3,
    run_e2e: bool = False,
    condition: str = "warm",
    judge: Any = None,
    provenance: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run a single task k times, return results.

    `provenance` is the run-set-wide block built by main() (harness commit,
    provider/model/effort, toolchain versions from the preflight). It is
    stamped onto every result together with this task's own prompt/spec
    fingerprint, so a re-run after any change to the harness or the task text
    is visibly a different experiment rather than a silently different one.
    """
    spec_path = task_dir / "spec.yaml"
    import yaml
    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    stack = spec["stack"]
    task_id = spec.get("id", task_dir.name)

    run_provenance: dict[str, Any] = {
        **(provenance or prov_mod.build_provenance(
            provider="unknown", model=getattr(adapter, "name", "unknown"),
            reasoning_effort=getattr(adapter, "reasoning_effort", None),
        )),
        "task": prov_mod.task_fingerprint(task_dir),
        "condition": condition,
        "k": k,
    }
    expects_artifacts = validity_mod.expects_artifacts(spec)

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

        result: dict[str, Any] = {
            "model": adapter.name,
            "task": task_id,
            "stack": stack,
            "run": run_idx,
            "condition": condition,
            # Reasoning effort pinned for this invocation (None if the model/
            # adapter doesn't support one). Recorded per run so cross-model
            # comparisons can confirm effort was held constant within a suite.
            "reasoning_effort": getattr(adapter, "reasoning_effort", None),
            "provenance": run_provenance,
            "stages": {},
        }

        # Materialize task, invoke model, run validation stages. Wrapped in
        # one try/except so a materialization failure (e.g. the chant
        # node_modules bootstrap's npm install) is recorded on this run's
        # result instead of crashing the whole matrix.
        try:
            task_info = materialize_task(task_dir, workspace, condition)
            prompt = task_info["prompt"]

            # Discover files in workspace (excluding node_modules -- a chant
            # workspace's symlinked node_modules is thousands of files the
            # model has no business seeing as "workspace files", and adapters
            # read+inline every file under 50KB into the prompt).
            workspace_files: list[Path] = []
            for f in sorted(workspace.rglob("*")):
                if not f.is_file() or f.name.startswith("."):
                    continue
                if "node_modules" in f.relative_to(workspace).parts:
                    continue
                workspace_files.append(f)

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

            # Run-validity gate (#59): two independent classifiers, ported in
            # parallel PRs and both kept (see bench/validity.py's module
            # docstring): the simple valid/reason shape score.py's
            # aggregate_scores reads, and the richer verdict/reasons shape
            # bench.validate and bench.report's integrity gates read. Stamped
            # together (disjoint key sets) so every consumer finds the field
            # it expects, and a run the gate rejects is documented with a
            # reason on the run JSON rather than scored as an ordinary
            # failure. Evaluated before the stages so the log line lands next
            # to the completion that caused it.
            simple_validity = check_run_validity(result)
            rich_validity = validity_mod.check_content(
                completion["content"],
                expects_artifacts=expects_artifacts,
                extracted_files=result.get("extracted_files"),
            )
            result["validity"] = {**simple_validity, **rich_validity}
            if result["validity"]["verdict"] != "valid":
                log.error(
                    "Run %s/%s#%d REJECTED by the validity gate: %s",
                    stack, task_id, run_idx, "; ".join(result["validity"]["reasons"]),
                )

            # Stage 1: lint
            if _stage_enabled(spec, "lint"):
                result["stages"]["lint"] = lint.run_lint(workspace, stack)
            else:
                result["stages"]["lint"] = {"skipped": True, "reason": "disabled by spec"}

            # Stage 2: static
            if _stage_enabled(spec, "static"):
                result["stages"]["static"] = static.run_static(workspace, stack)
            else:
                result["stages"]["static"] = {"skipped": True, "reason": "disabled by spec"}

            # Stage 3: semantic (runs in the model's workspace)
            if _stage_enabled(spec, "semantic"):
                result["stages"]["semantic"] = semantic.run_semantic(task_dir, workspace)
            else:
                result["stages"]["semantic"] = {"skipped": True, "reason": "disabled by spec"}

            # Stage 4: e2e (gated on both the --e2e flag and the spec)
            if run_e2e:
                if _stage_enabled(spec, "e2e"):
                    result["stages"]["e2e"] = e2e.run_e2e(workspace, stack)
                else:
                    result["stages"]["e2e"] = {"skipped": True, "reason": "disabled by spec"}

            # Rubric judge (flag-gated; spends API money, so default off).
            # Only rubric tasks return a verdict; a judge failure is recorded
            # but never fails the run — score.py falls back to idiom 0.0.
            if judge is not None:
                try:
                    verdict = judge.score_task(task_dir, workspace=workspace,
                                               content=completion["content"])
                    if verdict is not None:
                        result["judge"] = verdict
                except Exception as je:  # noqa: BLE001 - judging is best-effort
                    log.warning("Judge failed for %s: %s", task_id, je)
                    result["judge_error"] = str(je)

        except Exception as e:
            result["error"] = str(e)
            result["stages"]["lint"] = {"passed": False, "logs": str(e)}
            result.setdefault("validity", {
                "valid": False,
                "reason": "runner_error",
                "content_length": None,
                "verdict": "invalid",
                "reasons": [f"runner_error: {e}"],
                "checks": {},
            })

        results.append(result)

        # Clean workspace between runs
        shutil.rmtree(workspace, ignore_errors=True)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="IaC/CD Benchmark Runner")
    parser.add_argument("--model", required=True, help="Model identifier")
    parser.add_argument("--model-provider", default="anthropic",
                        choices=["anthropic", "openai-compat", "claude-cli"])
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
    parser.add_argument("--judge", action="store_true",
                        help="Score the idiom axis with the rubric LLM judge on tasks that "
                             "have a rubric (extra API calls; off by default)")
    parser.add_argument("--judge-model", default=None,
                        help=f"Judge model id (default: $BENCH_JUDGE_MODEL or "
                             f"{judge_mod.DEFAULT_JUDGE_MODEL})")
    parser.add_argument("--judge-provider", default="anthropic",
                        choices=["anthropic", "openai-compat", "claude-cli"],
                        help="Provider for the judge model (default: anthropic)")
    parser.add_argument("--judge-base-url", default=None,
                        help="Base URL for an OpenAI-compatible judge endpoint")
    parser.add_argument("--allow-missing-tools", action="store_true",
                        help="Start the run set even though a required binary for a "
                             "selected stack is missing. The whole result set is then "
                             "stamped partial and bench.validate refuses to publish it.")
    parser.add_argument("--results-tag", default=None,
                        help="Suffix tag for the results directory (e.g. 'low' -> results/<model>-low/). "
                             "Prevents re-runs with different settings from overwriting prior runs.")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Parse stacks
    all_stacks = ["knr-ops", "crossplane", "terraform", "pulumi-python", "pulumi-typescript", "chant", "bare"]
    stacks = [args.stack] if args.stack else (all_stacks if args.stacks == "all" else args.stacks.split(","))

    # Tooling-health preflight, before a single token is spent. A stage whose
    # binary is absent cannot tell a correct answer from an unchecked one, and
    # finding that out after a 90-run matrix has already been paid for is what
    # issue #56 cost. Refuses unless --allow-missing-tools.
    try:
        preflight_report = preflight_mod.check(
            stacks, include_e2e=args.e2e, allow_missing=args.allow_missing_tools,
        )
    except preflight_mod.PreflightError as e:
        print(preflight_mod.format_report(e.report), file=sys.stderr)
        print(f"\n{e}", file=sys.stderr)
        raise SystemExit(2) from e
    log.info("\n%s", preflight_mod.format_report(preflight_report))

    # Build adapter
    base_url: str | None = args.base_url

    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY") or "sk-placeholder"

    if args.model_provider == "anthropic":
        adapter: ModelAdapter = AnthropicAdapter(args.model, api_key,
                                                 reasoning_effort=args.reasoning_effort)
    elif args.model_provider == "claude-cli":
        # No API key involved: shells out to the locally-authenticated
        # `claude` CLI (OAuth / claude.ai login) instead of calling the API
        # directly. See ClaudeCliAdapter for what is and isn't pinnable.
        adapter = ClaudeCliAdapter(args.model, reasoning_effort=args.reasoning_effort)
    else:
        adapter = OpenAICompatAdapter(args.model, base_url or "http://localhost:8000", api_key,
                                      reasoning_effort=args.reasoning_effort)

    # Build the rubric judge (opt-in: it costs extra API calls)
    rubric_judge = None
    if args.judge:
        rubric_judge = judge_mod.build_judge(
            model=args.judge_model,
            provider=args.judge_provider,
            base_url=args.judge_base_url,
        )
        log.info("Rubric judge enabled: model=%s prompt=%s",
                 rubric_judge.model, judge_mod.prompt_hash())

    # Provenance stamped onto every run in this set.
    run_set_provenance = prov_mod.build_provenance(
        provider=args.model_provider,
        model=adapter.name,
        reasoning_effort=args.reasoning_effort,
        toolchain=preflight_report["toolchain"],
        partial=preflight_report["partial"],
        extra={
            "judge_model": getattr(rubric_judge, "model", None) if rubric_judge else None,
            "judge_prompt_sha256": judge_mod.prompt_hash() if rubric_judge else None,
        },
    )
    log.info(
        "Provenance: harness=%s%s toolchain=%s",
        run_set_provenance["harness"].get("commit"),
        " (dirty)" if run_set_provenance["harness"].get("dirty") else "",
        prov_mod.toolchain_fingerprint(preflight_report["toolchain"]),
    )

    # Discover tasks
    all_results: list[dict[str, Any]] = []
    for stack in stacks:
        stack_dir = TASKS_DIR / stack
        if not stack_dir.exists():
            log.warning("Stack dir not found: %s", stack_dir)
            continue

        if stack == "chant":
            preflight = e2e.preflight_chant_golden()
            if not preflight.get("passed", False) and not preflight.get("skipped", False):
                log.error(
                    "Skipping chant stack: golden-base/chant preflight failed:\n%s",
                    preflight.get("logs", ""),
                )
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
            results = run_task(task_dir, adapter, args.k, args.e2e, args.condition,
                               judge=rubric_judge, provenance=run_set_provenance)
            all_results.extend(results)

            # Write results
            model_name = adapter.name.replace("/", "-")
            if args.results_tag:
                model_name = f"{model_name}-{args.results_tag}"
            set_dir = RESULTS_DIR / model_name
            set_dir.mkdir(parents=True, exist_ok=True)
            # Set-level manifest: the preflight that authorised this run set.
            # Named with a leading underscore so score.load_result_set's
            # `"run" in stem` glob can never mistake it for a run.
            (set_dir / "_provenance.json").write_text(json.dumps({
                "provenance": run_set_provenance,
                "preflight": preflight_report,
            }, indent=2, default=str))
            result_dir = set_dir / stack / args.condition
            result_dir.mkdir(parents=True, exist_ok=True)
            for r in results:
                out_path = result_dir / f"{task_dir.name}_run{r['run']}.json"
                with open(out_path, "w") as f:
                    json.dump(r, f, indent=2, default=str)
                log.info("Wrote %s", out_path)

    # Summary. Rejected runs are named here rather than buried: a run the
    # gates rejected did not measure the model, and the count belongs next to
    # the pass count, not underneath it.
    total = len(all_results)
    passed = sum(1 for r in all_results if r["stages"].get("lint", {}).get("passed"))
    rejected = sum(
        1 for r in all_results
        if (r.get("validity") or {}).get("verdict", "valid") != "valid"
    )
    log.info("Summary: %d runs, %d passed lint, rejected: %d", total, passed, rejected)
    if rejected:
        log.warning(
            "%d of %d runs were rejected by the validity gate and must not be "
            "quoted as scores. Run `python3 -m bench.validate %s` for the reasons.",
            rejected, total, RESULTS_DIR / adapter.name.replace("/", "-"),
        )
    if preflight_report["partial"]:
        log.warning(
            "This result set is PARTIAL: it ran with %s missing.",
            ", ".join(preflight_report["missing"]),
        )


if __name__ == "__main__":
    main()
