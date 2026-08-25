"""
Integration tests for the benchmark runner.
Tests task materialization, stage runners, and result formats without needing a model.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import bench.runner as runner
from bench.grounding import SchemaCache

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"
RESULTS_DIR = ROOT / "results"


def test_runner_executes():
    """The runner can be invoked without crashing."""
    result = subprocess.run(
        [sys.executable, "-m", "bench.runner", "--help"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0
    assert "IaC/CD Benchmark Runner" in result.stdout
    assert "--grounding" in result.stdout


def test_grounding_validation_requires_non_empty_results_tag():
    with pytest.raises(ValueError, match="--grounding requires a non-empty --results-tag"):
        runner.validate_grounding_stacks(["knr-ops"], grounding=True, results_tag=None)

    with pytest.raises(ValueError, match="--grounding requires a non-empty --results-tag"):
        runner.validate_grounding_stacks(["knr-ops"], grounding=True, results_tag="")

    with pytest.raises(ValueError, match="--grounding requires a non-empty --results-tag"):
        runner.validate_grounding_stacks(["knr-ops"], grounding=True, results_tag="   ")


def test_non_grounded_validation_preserves_optional_results_tag():
    runner.validate_grounding_stacks(["terraform"], grounding=False, results_tag=None)


def test_grounding_validation_accepts_only_supported_stacks():
    runner.validate_grounding_stacks(
        ["knr-ops", "crossplane"], grounding=True, results_tag="grounded"
    )

    with pytest.raises(ValueError, match="supports knr-ops and crossplane only"):
        runner.validate_grounding_stacks(["terraform"], grounding=True, results_tag="grounded")


def test_grounding_validation_rejects_all_when_it_contains_unsupported_stacks():
    with pytest.raises(ValueError, match="unsupported stack.*pulumi-python"):
        runner.validate_grounding_stacks(
            runner.ALL_STACKS, grounding=True, results_tag="grounded"
        )


class CapturingAdapter(runner.ModelAdapter):
    def __init__(self):
        self.prompts = []

    @property
    def name(self):
        return "fake"

    def complete(self, prompt, files):
        self.prompts.append(prompt)
        return {"content": "No generated files.", "input_tokens": 1, "output_tokens": 1}


class FakeGroundingClient:
    def __init__(self, schema='{"type": "object"}'):
        self.schema = schema
        self.calls = []

    def get_schema(self, kind, api_version):
        self.calls.append((kind, api_version))
        return self.schema


def _grounded_task(tmp_path):
    task_dir = tmp_path / "T-grounded"
    (task_dir / "seed").mkdir(parents=True)
    (task_dir / "spec.yaml").write_text("id: T-grounded\nstack: knr-ops\n")
    (task_dir / "prompt.md").write_text("Write the manifest.\n")
    (task_dir / "seed" / "resource.yaml").write_text(
        "apiVersion: example.org/v1\nkind: Widget\nspec: {}\n"
    )
    return task_dir


def test_run_task_appends_grounding_prompt_and_records_metadata(tmp_path, monkeypatch):
    task_dir = _grounded_task(tmp_path)
    adapter = CapturingAdapter()
    client = FakeGroundingClient()
    cache = SchemaCache(tmp_path / "cache")
    monkeypatch.setattr(runner.lint, "run_lint", lambda *_: {"passed": True})
    monkeypatch.setattr(runner.static, "run_static", lambda *_: {"passed": True})
    monkeypatch.setattr(runner.semantic, "run_semantic", lambda *_: {"passed": True})

    results = runner.run_task(
        task_dir,
        adapter,
        1,
        False,
        "warm",
        grounding=True,
        grounding_client=client,
        grounding_cache=cache,
    )

    assert len(adapter.prompts) == 1
    assert "### Reference schemas" in adapter.prompts[0]
    assert '"type": "object"' in adapter.prompts[0]
    assert client.calls == [("Widget", "example.org/v1")]
    assert results[0]["grounding"]["kinds"] == ["example.org/v1/Widget"]
    section = "### Reference schemas" + adapter.prompts[0].split("### Reference schemas", 1)[1]
    assert results[0]["grounding"]["section_chars"] == len(section)
    assert "error" not in results[0]


def test_run_task_records_grounding_failure_without_invoking_model(tmp_path, monkeypatch):
    task_dir = _grounded_task(tmp_path)
    adapter = CapturingAdapter()

    class FailingClient:
        def get_schema(self, kind, api_version):
            raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(runner.lint, "run_lint", lambda *_: {"passed": True})

    results = runner.run_task(
        task_dir,
        adapter,
        1,
        False,
        "warm",
        grounding=True,
        grounding_client=FailingClient(),
        grounding_cache=SchemaCache(tmp_path / "cache"),
    )

    assert adapter.prompts == []
    assert results[0]["error"] == "grounding failed: catalog unavailable"
    assert results[0]["grounding"] == {"kinds": [], "section_chars": 0}
    assert results[0]["stages"]["lint"]["passed"] is False


def test_task_dirs_exist():
    """All 30 task directories exist."""
    stacks = ["knr-ops", "crossplane", "terraform", "pulumi-python", "pulumi-typescript"]
    task_names = ["T1-comprehend", "T2-generate", "T3-modify", "T4-debug", "T5-review", "T6-semantics"]
    for stack in stacks:
        for task in task_names:
            task_dir = TASKS_DIR / stack / task
            assert task_dir.exists(), f"Task dir missing: {task_dir}"
            assert (task_dir / "prompt.md").exists(), f"Prompt missing: {task_dir}"
            assert (task_dir / "spec.yaml").exists(), f"Spec missing: {task_dir}"


def test_semantics_tasks_have_graders():
    """T6-semantics tasks ship a seed, golden key, and 7-question grader."""
    stacks = ["knr-ops", "crossplane", "terraform", "pulumi-python", "pulumi-typescript"]
    for stack in stacks:
        t6 = TASKS_DIR / stack / "T6-semantics"
        assert (t6 / "seed").is_dir(), f"seed/ missing: {t6}"
        assert (t6 / "golden" / "answer_key.md").exists(), f"golden answer key missing: {t6}"
        test_file = t6 / "tests" / "test_task.py"
        assert test_file.exists(), f"grader missing: {t6}"
        source = test_file.read_text()
        graders = [l for l in source.splitlines() if l.startswith("def test_q")]
        assert len(graders) == 7, f"{stack} T6 grader should have 7 question tests, has {len(graders)}"


def test_semantics_golden_answers_pass_graders():
    """Every T6 golden answer key passes its own grader (and empty fails)."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate_t6.py")],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300,
    )
    assert result.returncode == 0, f"T6 self-validation failed:\n{result.stdout[-2000:]}"


def test_golden_implementations_exist():
    """Golden implementations have core files."""
    golden_dirs = ROOT / "golden-base"
    assert (golden_dirs / "knr-ops" / "clusters" / "eksa" / "cluster.yaml").exists()
    assert (golden_dirs / "crossplane" / "xrds" / "composite-web-service.yaml").exists()
    assert (golden_dirs / "terraform" / "infrastructure.tf").exists()
    assert (golden_dirs / "pulumi-python" / "__main__.py").exists()
    assert (golden_dirs / "pulumi-typescript" / "index.ts").exists()


def test_stage_runners_import():
    """Stage runners import cleanly."""
    from bench.stages import lint, static, semantic, e2e
    assert hasattr(lint, "run_lint")
    assert hasattr(static, "run_static")
    assert hasattr(semantic, "run_semantic")
    assert hasattr(e2e, "run_e2e")


def test_score_module_imports():
    """Score module imports cleanly."""
    from bench import score
    assert hasattr(score, "AXES")
    assert hasattr(score, "compute_score")
    assert hasattr(score, "aggregate_scores")


def test_report_module_imports():
    """Report module imports cleanly."""
    from bench import report
    assert hasattr(report, "main")


def test_model_adapters_import():
    """Model adapters import cleanly."""
    from bench.runner import AnthropicAdapter, OpenAICompatAdapter, ModelAdapter
    assert issubclass(AnthropicAdapter, ModelAdapter)
    assert issubclass(OpenAICompatAdapter, ModelAdapter)
