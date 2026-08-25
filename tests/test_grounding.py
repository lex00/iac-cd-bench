"""Tests for schema grounding module (network mocked)."""

import pytest

from bench.grounding import MCPClient, discover_kinds


class FakeResponse:
    def __init__(self, body, content_type="application/json"):
        self.text = body
        self.headers = {"content-type": content_type}


class FakeTransport:
    """Records posts and returns canned HTTP responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


def test_client_calls_get_schema_with_kind_and_apiversion():
    response = FakeResponse(
        '{"jsonrpc": "2.0", "id": 1, "result": '
        '{"content": [{"type": "text", "text": "{\\"description\\": \\"x\\"}"}]}}'
    )
    transport = FakeTransport([response])

    client = MCPClient(transport=transport)
    output = client.get_schema("Kustomization", "kustomize.toolkit.fluxcd.io/v1")

    assert output.startswith("{")
    sent = transport.posts[0]
    assert sent["url"] == "https://schemas.fluxoperator.dev/mcp"
    assert sent["headers"] == {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    assert sent["json"] == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "get_schema",
            "arguments": {
                "kind": "Kustomization",
                "apiVersion": "kustomize.toolkit.fluxcd.io/v1",
            },
        },
    }
    assert sent["timeout"] == 60.0


def test_client_calls_grep_catalog_with_query():
    response = FakeResponse(
        '{"jsonrpc": "2.0", "id": 1, "result": '
        '{"content": [{"type": "text", "text": "catalog hit"}]}}'
    )
    transport = FakeTransport([response])

    output = MCPClient(transport=transport).grep_catalog("Bucket")

    assert output == "catalog hit"
    assert transport.posts[0]["json"] == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "grep_catalog",
            "arguments": {"query": "Bucket"},
        },
    }


def test_client_parses_sse_framed_json_response():
    response = FakeResponse(
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"content":'
        '[{"type":"text","text":"sse hit"}]}}\n\n',
        content_type="text/event-stream",
    )
    transport = FakeTransport([response])

    output = MCPClient(transport=transport).grep_catalog("Kustomization")

    assert output == "sse hit"


def test_client_raises_for_json_rpc_error():
    response = FakeResponse(
        '{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"missing"}}'
    )
    transport = FakeTransport([response])

    with pytest.raises(RuntimeError, match="MCP error"):
        MCPClient(transport=transport).grep_catalog("missing")


def test_discover_kinds_finds_nested_yaml_documents_and_deduplicates(tmp_path):
    (tmp_path / "overlays" / "deep").mkdir(parents=True)
    (tmp_path / "overlays" / "deep" / "z.yaml").write_text(
        "---\n"
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "---\n"
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "spec:\n"
        "  template:\n"
        "    metadata: {}\n"
        "    spec: {}\n"
    )
    (tmp_path / "a.yml").write_text(
        "apiVersion: kustomize.toolkit.fluxcd.io/v1\n"
        "kind: Kustomization\n"
        "spec:\n"
        "  healthChecks:\n"
        "    - apiVersion: s3.services.k8s.aws/v1alpha1\n"
        "      kind: Bucket\n"
    )
    (tmp_path / "not_yaml.txt").write_text("apiVersion: v1\nkind: Secret\n")

    assert discover_kinds(tmp_path) == [
        ("apps/v1", "Deployment"),
        ("kustomize.toolkit.fluxcd.io/v1", "Kustomization"),
        ("s3.services.k8s.aws/v1alpha1", "Bucket"),
    ]


def test_discover_kinds_exempts_platform_example_org_resources(tmp_path):
    (tmp_path / "xrd.yaml").write_text(
        "apiVersion: platform.example.org/v1alpha1\n"
        "kind: WebService\n"
        "spec:\n"
        "  resources:\n"
        "    - apiVersion: platform.example.org/v1alpha1\n"
        "      kind: InternalResource\n"
    )
    (tmp_path / "real.yaml").write_text(
        "apiVersion: v1\n"
        "kind: Secret\n"
    )

    assert discover_kinds(tmp_path) == [("v1", "Secret")]
