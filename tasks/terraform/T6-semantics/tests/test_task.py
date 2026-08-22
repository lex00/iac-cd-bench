"""Semantic-understanding quiz grader — terraform T6."""

import json
import re
from pathlib import Path

import pytest


def _load_answers() -> dict:
    ws = Path(".")
    for c in sorted(ws.rglob("answers.json")):
        try:
            return json.loads(c.read_text())
        except Exception:
            continue
    out = ws / "model_output.md"
    if out.exists():
        blocks = re.findall(r"```json\s*\n(.*?)```", out.read_text(), re.DOTALL)
        for raw in reversed(blocks):
            try:
                return json.loads(raw)
            except Exception:
                continue
    pytest.fail("no parseable answers.json found in workspace or model_output.md")


@pytest.fixture(scope="module")
def answers() -> dict:
    return _load_answers()


def _norm(v) -> str:
    return str(v).strip().lower().replace("_", "-")


def test_q1_prevent_destroy_errors(answers):
    """Renaming the bucket forces replace, but prevent_destroy errors the plan."""
    assert "error" in _norm(answers.get("q1", "")), \
        f"q1: expected error, got {answers.get('q1')!r}"


def test_q2_count_shrink_destroys_highest_index(answers):
    """count 3->2 destroys private[2] only."""
    q2 = answers.get("q2") or []
    if isinstance(q2, str):
        q2 = [q2]
    normed = [_norm(x).replace(" ", "") for x in q2]
    assert len(normed) == 1 and "private[2]" in normed[0], \
        f"q2: expected [aws_subnet.private[2]], got {q2!r}"


def test_q3_count_to_foreach_recreates(answers):
    """count->for_each without moved blocks destroys and recreates."""
    assert "destroy" in _norm(answers.get("q3", "")), \
        f"q3: expected destroy-and-recreate-all, got {answers.get('q3')!r}"


def test_q4_ignore_changes_suppresses_config_drift(answers):
    """ignore_changes on engine_version: config edit shows no change."""
    assert "no-change" in _norm(answers.get("q4", "")), \
        f"q4: expected no-change, got {answers.get('q4')!r}"


def test_q5_ignore_changes_suppresses_remote_drift(answers):
    """ignore_changes also ignores out-of-band engine upgrades."""
    assert "no-change" in _norm(answers.get("q5", "")), \
        f"q5: expected no-change, got {answers.get('q5')!r}"


def test_q6_instance_class_updates_in_place(answers):
    """instance_class is updatable: in-place modify, not replace."""
    assert "update" in _norm(answers.get("q6", "")), \
        f"q6: expected update-in-place, got {answers.get('q6')!r}"


def test_q7_destroy_blocked_by_prevent_destroy(answers):
    """terraform destroy aborts on the prevent_destroy bucket."""
    q7 = answers.get("q7") or {}
    completes = q7.get("completes")
    if isinstance(completes, str):
        completes = completes.strip().lower() in ("true", "yes")
    assert completes is False, \
        f"q7 completes: expected false, got {q7.get('completes')!r}"
    assert "artifacts" in _norm(q7.get("blocking_resource", "")), \
        f"q7 blocking_resource: expected aws_s3_bucket.artifacts, got {q7.get('blocking_resource')!r}"
