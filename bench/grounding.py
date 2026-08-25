"""Schema grounding: fetch upstream CRD schemas from the Flux Schema MCP catalog."""

from __future__ import annotations

import json
from typing import Any


MCP_URL = "https://schemas.fluxoperator.dev/mcp"


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

    def get_schema(self, kind: str, api_version: str) -> str:
        result = self._call(
            "tools/call",
            {
                "name": "get_schema",
                "arguments": {"kind": kind, "apiVersion": api_version},
            },
        )
        return self._text(result)

    def grep_catalog(self, query: str) -> str:
        result = self._call(
            "tools/call",
            {"name": "grep_catalog", "arguments": {"query": query}},
        )
        return self._text(result)
