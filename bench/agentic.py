"""Agentic grounding arm: model-driven schema retrieval mid-generation.

The one-shot arm appends schemas blind (all seed kinds or nothing). This
module lets the model pull schemas itself: the adapter exposes
``grep_catalog`` and ``get_schema`` as tools, executes them against the MCP
catalog through the shared SchemaCache, and records a per-run trace so
results carry exactly what was retrieved and what it cost.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

from bench.grounding import SchemaCache

log = logging.getLogger(__name__)

# Hard caps so a degenerate loop cannot run forever or fetch without bound.
DEFAULT_MAX_TURNS = 24
DEFAULT_MAX_TOOL_CALLS = 40

AGENTIC_TOOLS_INSTRUCTION = """You have two tools for checking Kubernetes API schemas.

- grep_catalog(query): search the schema catalog for kinds matching a query.
  Use it to find which apiVersion/kind pairs exist when you are unsure.
- get_schema(kind, apiVersion): fetch the JSON Schema for one kind.

Call these BEFORE writing or reviewing manifests whenever you are not
certain of a field name, type, or required list. The schemas are
authoritative for grading."""


def openai_tools() -> list[dict[str, Any]]:
    """OpenAI-style tool definitions (also sent as-is by GLM/Kimi/Qwen)."""
    return [
        {
            "type": "function",
            "function": {
                "name": "grep_catalog",
                "description": (
                    "Search the Kubernetes schema catalog for kinds matching "
                    "a query; returns matching apiVersion/kind pairs."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search term, e.g. 'kustomization' or 'flux'",
                        }
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_schema",
                "description": (
                    "Fetch the JSON Schema for one Kubernetes kind. Returns "
                    "the authoritative CRD schema."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "description": "e.g. Kustomization"},
                        "apiVersion": {"type": "string", "description": "e.g. kustomize.toolkit.fluxcd.io/v1"},
                    },
                    "required": ["kind", "apiVersion"],
                },
            },
        },
    ]


def anthropic_tools() -> list[dict[str, Any]]:
    """Anthropic-style tool definitions."""
    return [
        {
            "name": "grep_catalog",
            "description": (
                "Search the Kubernetes schema catalog for kinds matching "
                "a query; returns matching apiVersion/kind pairs."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term, e.g. 'kustomization' or 'flux'",
                    }
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_schema",
            "description": (
                "Fetch the JSON Schema for one Kubernetes kind. Returns "
                "the authoritative CRD schema."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "description": "e.g. Kustomization"},
                    "apiVersion": {"type": "string", "description": "e.g. kustomize.toolkit.fluxcd.io/v1"},
                },
                "required": ["kind", "apiVersion"],
            },
        },
    ]


class _Executor(Protocol):
    """Anything with the two MCP tool methods (MCPClient, test fakes)."""

    def grep_catalog(self, query: str) -> str: ...

    def get_schema(self, kind: str, api_version: str) -> str: ...


class AgenticTrace:
    """Per-run record of tool calls and their cost."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.schemas_fetched: list[str] = []
        self.errors: list[str] = []

    def record(self, tool: str, args: dict[str, Any], result: str, error: str | None) -> None:
        entry: dict[str, Any] = {
            "tool": tool,
            "args": args,
            "result_chars": len(result),
        }
        if error is not None:
            entry["error"] = error
        self.calls.append(entry)
        if tool == "get_schema" and error is None:
            pair = f"{args.get('apiVersion', '?')}/{args.get('kind', '?')}"
            self.schemas_fetched.append(pair)
        if error is not None:
            self.errors.append(f"{tool}: {error}")

    def metadata(self, turns: int, model_calls: int) -> dict[str, Any]:
        """Shape written into result['agentic']."""
        return {
            "mode": "agentic",
            "turns": turns,
            "model_calls": model_calls,
            "tool_calls": len(self.calls),
            "schemas_fetched": sorted(set(self.schemas_fetched)),
            "schema_chars_fetched": sum(
                c["result_chars"] for c in self.calls if c["tool"] == "get_schema"
            ),
            "grep_calls": sum(1 for c in self.calls if c["tool"] == "grep_catalog"),
            "get_schema_calls": sum(1 for c in self.calls if c["tool"] == "get_schema"),
            "errors": self.errors,
        }


def _call_tool(
    executor: _Executor,
    cache: SchemaCache | None,
    name: str,
    args: dict[str, Any],
    trace: AgenticTrace,
) -> str:
    """Execute one tool call, tracing it; errors become tool-result text."""
    try:
        if name == "grep_catalog":
            query = str(args.get("query", ""))
            if not query.strip():
                raise ValueError("query must be a non-empty string")
            result = executor.grep_catalog(query)
        elif name == "get_schema":
            kind = str(args.get("kind", "")).strip()
            api_version = str(args.get("apiVersion", "")).strip()
            if not kind or not api_version:
                raise ValueError("get_schema requires kind and apiVersion")
            if cache is not None:
                result = cache.get(kind, api_version, executor.get_schema)
            else:
                result = executor.get_schema(kind, api_version)
        else:
            raise ValueError(f"unknown tool: {name}")
    except Exception as exc:  # noqa: BLE001 - tool errors feed back to the model
        error = _concise(exc)
        trace.record(name, args, "", error)
        return f"Tool error: {error}"
    trace.record(name, args, result, None)
    return result


def _concise(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    return text[:300]


def _max_result_chars(tool: str) -> int:
    # grep hits are short; schemas are the payload and already bounded by
    # the catalog's own size.
    return 2000 if tool == "grep_catalog" else 400_000


def run_agentic_completion(
    base_adapter: Any,
    prompt: str,
    workspace_files: list[Path],
    executor: _Executor,
    cache: SchemaCache | None = None,
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
) -> dict[str, Any]:
    """Drive the model/tool loop and return a complete()-shaped result.

    Works with both adapter families. Tool-schema style comes from the
    adapter's ``tool_schema_style`` attribute ("anthropic" or "openai",
    defaulting to openai); the per-turn message shape is detected from the
    request() response ("content_blocks" = Anthropic, "message" = OpenAI).
    """
    trace = AgenticTrace()
    provider = getattr(base_adapter, "tool_schema_style", "openai")
    tools = openai_tools() if provider == "openai" else anthropic_tools()

    # File sections appended to the initial user turn, matching each
    # adapter's complete() behavior for non-tool runs.
    file_sections: list[str] = []
    for f in workspace_files:
        if f.is_file() and f.stat().st_size < 50000:
            try:
                file_sections.append(f"File: {f.name}\n{f.read_text()}")
            except (UnicodeDecodeError, OSError):
                continue
    body = prompt
    if file_sections:
        body = prompt + "\n\n### Workspace files\n\n" + "\n\n".join(file_sections)

    # A single plain-text user turn is valid for both providers; the tool
    # instruction leads the body.
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": AGENTIC_TOOLS_INSTRUCTION + "\n\n" + body,
        }
    ]

    content_parts: list[str] = []
    total_input = 0
    total_output = 0
    turns = 0
    model_calls = 0
    stop = False

    while not stop and turns < max_turns:
        turns += 1
        data = base_adapter.request(messages, tools=tools)
        model_calls += 1
        total_input += data.get("input_tokens", 0)
        total_output += data.get("output_tokens", 0)
        anthropic_shape = "content_blocks" in data

        if not anthropic_shape:
            msg = data["message"]
            text = msg.get("content")
            if text:
                content_parts.append(text)
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                stop = True
                break
            messages.append(msg)
            follow_up: list[dict[str, Any]] = []
            for tc in tool_calls:
                if trace.calls and len(trace.calls) >= max_tool_calls:
                    # Let the model know it is cut off, then require text.
                    follow_up.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": "Tool call budget exhausted; answer without further tools.",
                        }
                    )
                    continue
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = _call_tool(executor, cache, name, args, trace)
                follow_up.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": result[: _max_result_chars(tool=name)]}
                )
            messages.extend(follow_up)
        else:
            blocks = data["content_blocks"]
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            if text:
                content_parts.append(text)
            tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
            if not tool_uses:
                stop = True
                break
            messages.append({"role": "assistant", "content": blocks})
            follow_up_blocks: list[dict[str, Any]] = []
            for tu in tool_uses:
                if trace.calls and len(trace.calls) >= max_tool_calls:
                    follow_up_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": "Tool call budget exhausted; answer without further tools.",
                        }
                    )
                    continue
                result = _call_tool(executor, cache, tu["name"], tu.get("input") or {}, trace)
                follow_up_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": result[: _max_result_chars(tool=tu["name"])],
                    }
                )
            messages.append({"role": "user", "content": follow_up_blocks})

    if turns >= max_turns and not stop:
        log.warning("Agentic loop hit max_turns=%d; returning partial content", max_turns)

    return {
        "content": "\n\n".join(p for p in content_parts if p.strip()),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "agentic": trace.metadata(turns=turns, model_calls=model_calls),
    }
