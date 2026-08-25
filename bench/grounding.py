"""Schema grounding: fetch upstream CRD schemas from the Flux Schema MCP catalog."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


MCP_URL = "https://schemas.fluxoperator.dev/mcp"
EXEMPT_GROUPS = ("platform.example.org",)
JSON_SCHEMA_KEYS = frozenset(
    {
        "$id",
        "$ref",
        "$schema",
        "$defs",
        "additionalItems",
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "contains",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "default",
        "dependentRequired",
        "dependentSchemas",
        "deprecated",
        "description",
        "else",
        "enum",
        "examples",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "if",
        "items",
        "maxContains",
        "maximum",
        "maxItems",
        "maxLength",
        "maxProperties",
        "minContains",
        "minimum",
        "minItems",
        "minLength",
        "minProperties",
        "multipleOf",
        "not",
        "oneOf",
        "pattern",
        "patternProperties",
        "prefixItems",
        "properties",
        "propertyNames",
        "readOnly",
        "required",
        "then",
        "title",
        "type",
        "unevaluatedItems",
        "unevaluatedProperties",
        "uniqueItems",
        "writeOnly",
    }
)


def discover_kinds(workspace: Path) -> list[tuple[str, str]]:
    """Return deterministic, unique ``(apiVersion, kind)`` pairs in YAML files."""
    pairs: set[tuple[str, str]] = set()
    yaml_paths = sorted(
        path
        for path in workspace.rglob("*")
        if path.is_file() and path.suffix in {".yaml", ".yml"}
    )

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            api_version = node.get("apiVersion")
            kind = node.get("kind")
            if (
                isinstance(api_version, str)
                and isinstance(kind, str)
                and api_version
                and kind
                and api_version.split("/", 1)[0] not in EXEMPT_GROUPS
            ):
                pairs.add((api_version, kind))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    for path in yaml_paths:
        try:
            text = path.read_text(encoding="utf-8")
            documents = list(yaml.safe_load_all(text))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        for document in documents:
            visit(document)

    return sorted(pairs)


class MCPClient:
    """Stateless streamable-HTTP JSON-RPC client for the MCP catalog."""

    def __init__(
        self,
        transport: Any | None = None,
        url: str = MCP_URL,
        timeout: float = 60.0,
    ) -> None:
        self._url = url
        self._timeout = timeout
        if transport is None:
            import httpx

            self._transport = httpx.Client(timeout=timeout)
        else:
            self._transport = transport
        self._next_id = 0

    def _call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
        }
        if params:
            payload["params"] = params

        response = self._transport.post(
            self._url,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json=payload,
            timeout=self._timeout,
        )
        data = self._parse(response)
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        return data.get("result", {})

    @staticmethod
    def _parse(response: Any) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        body = response.text
        if "text/event-stream" in content_type:
            for line in body.splitlines():
                if line.startswith("data:"):
                    try:
                        return json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
            raise RuntimeError("SSE response with no parsable data frame")
        return json.loads(body)

    @staticmethod
    def _text(result: dict[str, Any]) -> str:
        return result["content"][0]["text"]

    @staticmethod
    def _validate_schema_text(schema: str, kind: str, api_version: str) -> str:
        try:
            payload = json.loads(schema)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"MCP get_schema returned invalid JSON for {kind} ({api_version}); "
                "grounding cannot continue"
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError(
                f"MCP get_schema returned JSON that is not a recognizable JSON Schema "
                f"for {kind} ({api_version}); grounding cannot continue"
            )

        keys = {str(key).lower() for key in payload}
        status = str(payload.get("status", "")).lower()
        if (
            {"error", "errors", "message", "detail", "limit"}.intersection(keys)
            or status in {"error", "failed", "failure"}
        ):
            raise RuntimeError(
                f"MCP get_schema returned an error/limit payload for {kind} "
                f"({api_version}); grounding cannot continue"
            )

        if not set(payload).intersection(JSON_SCHEMA_KEYS):
            raise RuntimeError(
                f"MCP get_schema returned JSON that is not a recognizable JSON Schema "
                f"for {kind} ({api_version}); grounding cannot continue"
            )
        return schema

    def get_schema(self, kind: str, api_version: str) -> str:
        result = self._call(
            "tools/call",
            {
                "name": "get_schema",
                "arguments": {"kind": kind, "apiVersion": api_version},
            },
        )
        return self._validate_schema_text(self._text(result), kind, api_version)

    def grep_catalog(self, query: str) -> str:
        result = self._call(
            "tools/call",
            {"name": "grep_catalog", "arguments": {"query": query}},
        )
        return self._text(result)


class SchemaCache:
    """Disk cache keyed by kind and apiVersion; fetch on cache misses."""

    def __init__(self, cache_dir: Path) -> None:
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(kind: str, api_version: str) -> str:
        """Return a deterministic filename containing no path separators."""
        raw = f"{kind}_{api_version}".replace("/", "_").replace("\\", "_")
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", raw)
        return f"{safe}.json"

    def _path(self, kind: str, api_version: str) -> Path:
        root = self.dir.resolve()
        path = (self.dir / self._key(kind, api_version)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("schema cache path escapes cache directory") from exc
        return path

    def get(self, kind: str, api_version: str, fetch) -> str:
        path = self._path(kind, api_version)
        if path.exists():
            return path.read_text(encoding="utf-8")
        schema = fetch(kind, api_version)
        path.write_text(schema, encoding="utf-8")
        return schema

    def warm(self, pairs: list[tuple[str, str]], client: MCPClient) -> int:
        """Prefetch pairs and return the number fetched from the client."""
        fetched = 0
        for api_version, kind in pairs:
            path = self._path(kind, api_version)
            if not path.exists():
                self.get(kind, api_version, client.get_schema)
                fetched += 1
        return fetched


def _safe_schema_payload(schema: str) -> str:
    """Return schema text suitable for a JSON-labelled fenced block."""
    try:
        json.loads(schema)
    except (TypeError, json.JSONDecodeError):
        return json.dumps(
            {"raw_schema": str(schema)},
            ensure_ascii=False,
            indent=2,
        )
    return schema


def _fence_delimiter(text: str) -> str:
    """Choose a deterministic Markdown fence longer than embedded backticks."""
    longest = max((len(match) for match in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def build_grounding_section(schemas: dict[tuple[str, str], str]) -> str:
    """Build a deterministic, authoritative reference section for schema text."""
    lines = ["### Reference schemas (upstream CRD definitions)", ""]
    for (api_version, kind), schema in sorted(schemas.items()):
        payload = _safe_schema_payload(schema)
        fence = _fence_delimiter(payload)
        lines.extend(
            [
                f"Schema for `{kind}` (`{api_version}`):",
                "",
                f"{fence}json",
                payload,
                fence,
                "",
            ]
        )
    lines.append(
        "Use these schemas when writing or reviewing manifests. "
        "Field names and constraints are authoritative."
    )
    return "\n".join(lines)
