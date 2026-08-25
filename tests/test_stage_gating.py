"""
Tests for scored-run integrity fixes (issue #56):

1. run_task honors spec.yaml's stages.<name>.enabled and records
   {"skipped": True, "reason": "disabled by spec"} instead of running a
   disabled stage; score.py's correctness axis excludes skipped stages from
   both numerator and denominator.
2. lint.py / static.py set passed=False (with a loud log line) when a stage
   tool binary is missing (FileNotFoundError), matching the timeout and
   non-zero-exit branches instead of silently passing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bench import runner
from bench.score import compute_score
from bench.stages import lint, static

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "tasks"

T1_COMPREHEND = TASKS_DIR / "knr-ops" / "T1-comprehend"  # all stages disabled
T2_GENERATE = TASKS_DIR / "knr-ops" / "T2-generate"  # lint/static/semantic enabled


class StubModel:
    name = "stub-model"

    def __init__(self, content: str = "the model's answer"):
        self._content = content

    def complete(self, prompt, files):
        return {"content": self._content, "input_tokens": 1, "output_tokens": 2}


# ── run_task stage gating ───────────────────────────────────────────────

def test_disabled_stages_are_skipped_not_run():
    """T1-comprehend disables lint/static/semantic/e2e; run_task must record
    each as skipped rather than actually invoking the stage runners (which
    would otherwise trivially "pass" on an empty workspace and mask a
    missing-binary bug, per issue #56)."""
    results = runner.run_task(T1_COMPREHEND, StubModel(), k=1)
    assert len(results) == 1
    stages = results[0]["stages"]

    for name in ("lint", "static", "semantic"):
        assert stages[name] == {"skipped": True, "reason": "disabled by spec"}


def test_enabled_stages_still_run():
    """T2-generate enables lint/static/semantic; run_task must still execute
    them (not skip), i.e. gating is stage-by-stage per spec, not blanket."""
    results = runner.run_task(T2_GENERATE, StubModel(), k=1)
    assert len(results) == 1
    stages = results[0]["stages"]

    for name in ("lint", "static", "semantic"):
        assert "skipped" not in stages[name]
        assert "passed" in stages[name]


def test_stage_enabled_defaults_true_when_spec_omits_stages_block():
    assert runner._stage_enabled({}, "lint") is True
    assert runner._stage_enabled({"stages": {}}, "lint") is True
    assert runner._stage_enabled({"stages": {"lint": {}}}, "lint") is True
    assert runner._stage_enabled({"stages": {"lint": {"enabled": False}}}, "lint") is False
    assert runner._stage_enabled({"stages": {"lint": {"enabled": True}}}, "lint") is True


# ── score.py correctness excludes skipped stages ───────────────────────

def test_correctness_excludes_skipped_stages_from_denominator():
    result = {
        "stages": {
            "lint": {"skipped": True, "reason": "disabled by spec"},
            "static": {"skipped": True, "reason": "disabled by spec"},
            "semantic": {"skipped": True, "reason": "disabled by spec"},
        }
    }
    # Nothing ran: correctness must not default to a spurious pass.
    assert compute_score(result)["correctness"] == 0


def test_correctness_averages_only_over_attempted_stages():
    result = {
        "stages": {
            "lint": {"passed": True},
            "static": {"skipped": True, "reason": "disabled by spec"},
            "semantic": {"passed": False},
        }
    }
    # lint passed, semantic failed, static skipped (excluded): 1/2, not 1/3.
    assert compute_score(result)["correctness"] == 0.5


def test_correctness_never_counts_a_skip_as_a_pass():
    result = {
        "stages": {
            "lint": {"passed": True},
            "static": {"skipped": True, "reason": "disabled by spec"},
            "semantic": {"passed": True},
        }
    }
    scores = compute_score(result)
    assert scores["correctness"] == 1.0  # 2/2 attempted, not 2/3


def test_end_to_end_disabled_task_scores_honestly():
    """Full pipeline for a pure-rubric task (all stages disabled): run_task
    skips every stage, and compute_score must not report correctness: 1.0 —
    the exact bug this fix closes."""
    results = runner.run_task(T1_COMPREHEND, StubModel(), k=1)
    scores = compute_score(results[0])
    assert scores["correctness"] == 0


# ── missing-binary honesty (lint.py / static.py) ────────────────────────

def _raise_not_found(*args, **kwargs):
    raise FileNotFoundError("no such file or directory: fake-binary")


def test_lint_missing_binary_sets_passed_false(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(subprocess, "run", _raise_not_found)
    # terraform stack always runs commands (no "nothing to lint" early return).
    result = lint.run_lint(tmp_path, "terraform")
    assert result["passed"] is False
    assert "NOT FOUND" in result["logs"]


@pytest.mark.parametrize("stack,setup", [
    ("terraform", lambda ws: None),
    ("pulumi-python", lambda ws: None),
])
def test_static_missing_binary_sets_passed_false(tmp_path, monkeypatch, stack, setup):
    setup(tmp_path)
    monkeypatch.setattr(subprocess, "run", _raise_not_found)
    result = static.run_static(tmp_path, stack)
    assert result["passed"] is False
    assert "NOT FOUND" in result["logs"]


def test_static_bare_missing_kubectl_sets_passed_false(tmp_path, monkeypatch):
    (tmp_path / "manifest.yaml").write_text("apiVersion: v1\nkind: ConfigMap\n")
    monkeypatch.setattr(subprocess, "run", _raise_not_found)
    result = static.run_static(tmp_path, "bare")
    assert result["passed"] is False


def test_static_chant_missing_binary_sets_passed_false(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _raise_not_found)
    result = static.run_static(tmp_path, "chant")
    assert result["passed"] is False
