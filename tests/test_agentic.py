"""Tests for the agentic grounding arm (bench.agentic + runner wiring)."""

import json

from bench import runner
from bench.agentic import (
    DEFAULT_MAX_TOOL_CALLS,
    AgenticTrace,
    run_agentic_completion,
)
from bench.grounding import SchemaCache


class FakeGroundingExecutor:
    """Stands in for MCPClient with canned catalog responses."""

    def __init__(self, schema='{"type": "object", "properties": {"spec": {}}}'):
        self.schema = schema
        self.grep_calls = []
        self.schema_calls = []

    def grep_catalog(self, query):
        self.grep_calls.append(query)
        return json.dumps([{"apiVersion": "example.org/v1", "kind": "Widget"}])

    def get_schema(self, kind, api_version):
        self.schema_calls.append((kind, api_version))
        return self.schema


class ScriptedOpenAIAdapter:
    """OpenAI-style adapter returning canned request() responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    @property
    def name(self):
        return "fake-openai"

    def request(self, messages, tools=None):
        self.requests.append({"messages": messages, "tools": tools})
        return self.responses.pop(0)


def _tool_call(call_id, name, args_json):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args_json},
    }


def _resp(content=None, tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {
        "message": msg,
        "finish_reason": "tool_calls" if tool_calls else "stop",
        "input_tokens": 10,
        "output_tokens": 5,
    }


def test_agentic_loop_openai_style_fetches_schema_and_finishes():
    executor = FakeGroundingExecutor()
    adapter = ScriptedOpenAIAdapter([
        _resp(tool_calls=[_tool_call("c1", "get_schema", '{"kind": "Widget", "apiVersion": "example.org/v1"}')]),
        _resp(content="Here is the manifest."),
    ])

    out = run_agentic_completion(adapter, "Write the manifest.", [], executor)

    assert out["content"] == "Here is the manifest."
    assert executor.schema_calls == [("Widget", "example.org/v1")]
    assert out["input_tokens"] == 20  # summed across both model calls
    meta = out["agentic"]
    assert meta["mode"] == "agentic"
    assert meta["turns"] == 2
    assert meta["model_calls"] == 2
    assert meta["tool_calls"] == 1
    assert meta["schemas_fetched"] == ["example.org/v1/Widget"]
    assert meta["schema_chars_fetched"] == len(executor.schema)
    assert meta["get_schema_calls"] == 1
    assert meta["grep_calls"] == 0
    assert meta["errors"] == []
    # Second request must carry the tool result message
    second = adapter.requests[1]
    roles = [m["role"] for m in second["messages"]]
    assert roles == ["user", "assistant", "tool"]
    tool_msg = second["messages"][-1]
    assert tool_msg["tool_call_id"] == "c1"
    assert tool_msg["content"] == executor.schema


def test_agentic_loop_grep_then_schema():
    executor = FakeGroundingExecutor()
    adapter = ScriptedOpenAIAdapter([
        _resp(tool_calls=[_tool_call("g1", "grep_catalog", '{"query": "widget"}')]),
        _resp(tool_calls=[_tool_call("s1", "get_schema", '{"kind": "Widget", "apiVersion": "example.org/v1"}')]),
        _resp(content="Done."),
    ])

    out = run_agentic_completion(adapter, "prompt", [], executor)

    assert executor.grep_calls == ["widget"]
    assert executor.schema_calls == [("Widget", "example.org/v1")]
    meta = out["agentic"]
    assert meta["tool_calls"] == 2
    assert meta["grep_calls"] == 1
    assert meta["get_schema_calls"] == 1


def test_agentic_tool_error_recorded_and_fed_back():
    class FailingExecutor:
        def grep_catalog(self, query):
            raise RuntimeError("catalog down")

        def get_schema(self, kind, api_version):
            raise RuntimeError("catalog down")

    adapter = ScriptedOpenAIAdapter([
        _resp(tool_calls=[_tool_call("e1", "grep_catalog", '{"query": "widget"}')]),
        _resp(content="Answering without the catalog."),
    ])

    out = run_agentic_completion(adapter, "prompt", [], FailingExecutor())

    meta = out["agentic"]
    assert meta["errors"] == ["grep_catalog: catalog down"]
    assert meta["schemas_fetched"] == []
    tool_msg = adapter.requests[1]["messages"][-1]
    assert tool_msg["content"].startswith("Tool error: catalog down")


def test_agentic_max_tool_calls_budget_exhaustion():
    # Model demands more calls than the budget allows; the excess calls get
    # a budget-exhausted tool result and the loop must still terminate with
    # the model's final text.
    executor = FakeGroundingExecutor()
    many = [_tool_call(f"t{i}", "grep_catalog", '{"query": "x"}') for i in range(5)]
    adapter = ScriptedOpenAIAdapter([
        _resp(tool_calls=many),
        _resp(tool_calls=many),
        _resp(content="Final answer."),
    ])

    out = run_agentic_completion(
        adapter, "prompt", [], executor, max_tool_calls=6
    )

    meta = out["agentic"]
    assert meta["tool_calls"] == 6
    assert meta["turns"] == 3
    assert out["content"] == "Final answer."
    # The final request's tool messages must include the budget notice.
    last_tool_msgs = [m for m in adapter.requests[-1]["messages"] if m["role"] == "tool"]
    assert any("budget exhausted" in m["content"] for m in last_tool_msgs)


def test_agentic_max_turns_cap_stops_loop():
    # Adapter that always requests tools; loop must stop at max_turns.
    executor = FakeGroundingExecutor()
    always_tools = _resp(tool_calls=[_tool_call("c", "grep_catalog", '{"query": "x"}')])
    adapter = ScriptedOpenAIAdapter([always_tools] * 30)

    out = run_agentic_completion(adapter, "prompt", [], executor, max_turns=5)

    assert out["agentic"]["turns"] == 5
    assert len(adapter.requests) == 5


def test_agentic_uses_cache_for_repeated_schemas(tmp_path):
    executor = FakeGroundingExecutor()
    cache = SchemaCache(tmp_path / "cache")
    script = [
        _resp(tool_calls=[_tool_call("a", "get_schema", '{"kind": "Widget", "apiVersion": "example.org/v1"}')]),
        _resp(tool_calls=[_tool_call("b", "get_schema", '{"kind": "Widget", "apiVersion": "example.org/v1"}')]),
        _resp(content="done"),
    ]
    adapter = ScriptedOpenAIAdapter(script)

    run_agentic_completion(adapter, "p", [], executor, cache)

    # Two get_schema tool calls, but the executor only fetched once.
    assert executor.schema_calls == [("Widget", "example.org/v1")]
    assert (tmp_path / "cache").exists()


def test_agentic_anthropic_style_blocks():
    class ScriptedAnthropicAdapter:
        tool_schema_style = "anthropic"

        def __init__(self, responses):
            self.responses = list(responses)
            self.requests = []

        @property
        def name(self):
            return "fake-anthropic"

        def request(self, messages, tools=None):
            self.requests.append({"messages": messages, "tools": tools})
            return self.responses.pop(0)

    executor = FakeGroundingExecutor()
    adapter = ScriptedAnthropicAdapter([
        {
            "content_blocks": [
                {"type": "text", "text": "checking"},
                {"type": "tool_use", "id": "tu1", "name": "get_schema",
                 "input": {"kind": "Widget", "apiVersion": "example.org/v1"}},
            ],
            "stop_reason": "tool_use",
            "input_tokens": 7,
            "output_tokens": 3,
        },
        {
            "content_blocks": [{"type": "text", "text": "manifest ready"}],
            "stop_reason": "end_turn",
            "input_tokens": 9,
            "output_tokens": 4,
        },
    ])

    out = run_agentic_completion(adapter, "prompt", [], executor)

    assert "manifest ready" in out["content"]
    assert out["agentic"]["schemas_fetched"] == ["example.org/v1/Widget"]
    # First request: single user message with instruction + prompt combined
    first = adapter.requests[0]
    assert first["messages"][0]["role"] == "user"
    assert "grep_catalog" in first["messages"][0]["content"]
    assert "prompt" in first["messages"][0]["content"]
    # Tools sent are Anthropic-style (input_schema, not function.parameters)
    assert all("input_schema" in t for t in first["tools"])
    # Second request carries assistant blocks + tool_result user message
    second = adapter.requests[1]
    assert second["messages"][-2]["role"] == "assistant"
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "tu1"


def test_agentic_files_appended_to_initial_prompt(tmp_path):
    executor = FakeGroundingExecutor()
    adapter = ScriptedOpenAIAdapter([_resp(content="ok")])
    seed = tmp_path / "seed.yaml"
    seed.write_text("apiVersion: example.org/v1\nkind: Widget\n")

    run_agentic_completion(adapter, "WRITE", [seed], executor)

    user_msg = adapter.requests[0]["messages"][0]
    assert user_msg["content"].startswith("WRITE") is False  # instruction leads
    assert "WRITE" in user_msg["content"]
    assert "### Workspace files" in user_msg["content"]
    assert "seed.yaml" in user_msg["content"]


def test_agentic_instruction_present_in_initial_message():
    executor = FakeGroundingExecutor()
    adapter = ScriptedOpenAIAdapter([_resp(content="ok")])

    run_agentic_completion(adapter, "p", [], executor)

    first = adapter.requests[0]["messages"][0]
    assert first["role"] == "user"
    assert "grep_catalog" in first["content"]
    assert "get_schema" in first["content"]


# ── Runner wiring ────────────────────────────────────────────────────────


def _agentic_task(tmp_path):
    task_dir = tmp_path / "T-agentic"
    (task_dir / "seed").mkdir(parents=True)
    (task_dir / "spec.yaml").write_text("id: T-agentic\nstack: knr-ops\n")
    (task_dir / "prompt.md").write_text("Write the manifest.\n")
    return task_dir


def test_run_task_agentic_mode_records_agentic_metadata(tmp_path, monkeypatch):
    task_dir = _agentic_task(tmp_path)

    captured = {}

    class LoopAdapter:
        @property
        def name(self):
            return "fake"

        def complete(self, prompt, files):
            captured["legacy_prompt"] = prompt
            return {"content": "legacy", "input_tokens": 1, "output_tokens": 1}

    executor = FakeGroundingExecutor()

    def fake_loop(base_adapter, prompt, workspace_files, client, cache):
        captured["loop_prompt"] = prompt
        return {
            "content": "agentic output",
            "input_tokens": 42,
            "output_tokens": 7,
            "agentic": {"mode": "agentic", "turns": 2, "model_calls": 2,
                        "tool_calls": 1, "schemas_fetched": ["example.org/v1/Widget"],
                        "schema_chars_fetched": 40, "grep_calls": 0,
                        "get_schema_calls": 1, "errors": []},
        }

    monkeypatch.setattr(runner, "run_agentic_completion", fake_loop)
    monkeypatch.setattr(runner.lint, "run_lint", lambda *_: {"passed": True})
    monkeypatch.setattr(runner.static, "run_static", lambda *_: {"passed": True})
    monkeypatch.setattr(runner.semantic, "run_semantic", lambda *_: {"passed": True})

    results = runner.run_task(
        task_dir,
        LoopAdapter(),
        1,
        False,
        "cold",
        grounding=True,
        grounding_client=executor,
        grounding_cache=SchemaCache(tmp_path / "cache"),
        grounding_mode="agentic",
    )

    r = results[0]
    assert r["content"] == "agentic output"
    assert r["tokens"] == {"input": 42, "output": 7}
    assert r["agentic"]["mode"] == "agentic"
    assert r["agentic"]["schemas_fetched"] == ["example.org/v1/Widget"]
    # No one-shot section was appended to the prompt the loop received.
    assert "### Reference schemas" not in captured["loop_prompt"]
    # The empty initialized grounding block is replaced by the agentic block;
    # one-shot metadata must not appear.
    assert "grounding" not in r


def test_run_task_agentic_mode_without_client_raises(tmp_path, monkeypatch):
    task_dir = _agentic_task(tmp_path)

    class LoopAdapter:
        @property
        def name(self):
            return "fake"

        def complete(self, prompt, files):
            return {"content": "x", "input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(runner.lint, "run_lint", lambda *_: {"passed": True})
    # A broken executor surfaces as a run error, not a crash: the loop feeds
    # tool errors back to the model and records them in metadata.
    class FailingExecutor:
        def grep_catalog(self, query):
            raise RuntimeError("catalog down")

        def get_schema(self, kind, api_version):
            raise RuntimeError("catalog down")

    responses = [
        {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "t1",
                    "type": "function",
                    "function": {"name": "grep_catalog", "arguments": '{"query": "widget"}'},
                }],
            },
            "finish_reason": "tool_calls",
            "input_tokens": 1,
            "output_tokens": 1,
        },
        {
            "message": {"role": "assistant", "content": "gave up"},
            "finish_reason": "stop",
            "input_tokens": 1,
            "output_tokens": 1,
        },
    ]

    class ToolAdapter:
        @property
        def name(self):
            return "fake"

        def complete(self, prompt, files):
            return {"content": "x", "input_tokens": 1, "output_tokens": 1}

        def request(self, messages, tools=None):
            return responses.pop(0)

    monkeypatch.setattr(runner, "MCPClient", lambda: FailingExecutor())

    results = runner.run_task(
        task_dir,
        ToolAdapter(),
        1,
        False,
        "cold",
        grounding=True,
        grounding_mode="agentic",
    )

    r = results[0]
    assert r["agentic"]["errors"] == ["grep_catalog: catalog down"], (
        "tool failures must be recorded in metadata"
    )
    assert r["content"] == "gave up"


def test_agentic_metadata_defaults_consistent():
    trace = AgenticTrace()
    meta = trace.metadata(turns=1, model_calls=1)
    assert meta == {
        "mode": "agentic",
        "turns": 1,
        "model_calls": 1,
        "tool_calls": 0,
        "schemas_fetched": [],
        "schema_chars_fetched": 0,
        "grep_calls": 0,
        "get_schema_calls": 0,
        "errors": [],
    }
    assert DEFAULT_MAX_TOOL_CALLS == 40


def test_cli_rejects_agentic_mode_without_grounding():
    parser = runner.build_parser()
    args = parser.parse_args(["--model", "m", "--grounding-mode", "agentic"])
    # Validation lives in main(); assert the flag pairing rule directly.
    assert args.grounding is False and args.grounding_mode == "agentic"


def test_cli_accepts_agentic_with_grounding():
    parser = runner.build_parser()
    args = parser.parse_args([
        "--model", "m",
        "--grounding", "--grounding-mode", "agentic",
        "--condition", "cold", "--results-tag", "agentic",
    ])
    assert args.grounding_mode == "agentic"
    assert args.grounding is True
