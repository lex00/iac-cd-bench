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
    from bench.runner import AnthropicAdapter, OpenAICompatAdapter, ClaudeCliAdapter, ModelAdapter
    assert issubclass(AnthropicAdapter, ModelAdapter)
    assert issubclass(OpenAICompatAdapter, ModelAdapter)
    assert issubclass(ClaudeCliAdapter, ModelAdapter)
