"""Semantic-understanding quiz grader — pulumi-python T6."""

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
        text = out.read_text()
        # Accept any fence info string (```json, ```answers.json, bare ```, etc.)
        blocks = re.findall(r"```([\w.-]*)[ \t]*\n(.*?)```", text, re.DOTALL)
        for _info, raw in reversed(blocks):
            raw = raw.strip()
            if not raw.startswith("{"):
                continue
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


def _as_bool(v):
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes")
    return v


def test_q1_protect_blocks_destroy(answers):
    """protect=True on artifacts blocks pulumi destroy."""
    q1 = answers.get("q1") or {}
    assert _as_bool(q1.get("completes")) is False, \
        f"q1 completes: expected false, got {q1.get('completes')!r}"
    assert "artifact" in _norm(q1.get("blocking_resource", "")), \
        f"q1 blocking_resource: expected artifacts, got {q1.get('blocking_resource')!r}"


def test_q2_logical_rename_replaces(answers):
    """Renaming the logical resource name changes the URN: replacement."""
    assert "replace" in _norm(answers.get("q2", "")), \
        f"q2: expected replace, got {answers.get('q2')!r}"


def test_q3_secret_propagates_to_export(answers):
    """Secret config stays masked in stack output."""
    assert "mask" in _norm(answers.get("q3", "")), \
        f"q3: expected masked, got {answers.get('q3')!r}"


def test_q4_delete_before_replace(answers):
    """delete_before_replace inverts default create-before-delete."""
    assert "delete-then-create" in _norm(answers.get("q4", "")), \
        f"q4: expected delete-then-create, got {answers.get('q4')!r}"


def test_q5_stack_config_wins(answers):
    """replicas=4 from stack config; removal falls back to code default."""
    q5 = answers.get("q5") or {}
    try:
        value = int(q5.get("value"))
    except (TypeError, ValueError):
        value = None
    assert value == 4, f"q5 value: expected 4, got {q5.get('value')!r}"
    assert _as_bool(q5.get("changes_if_removed")) is True, \
        f"q5 changes_if_removed: expected true, got {q5.get('changes_if_removed')!r}"


def test_q6_outputs_unknown_at_preview(answers):
    """Fresh-stack preview: bucket ARN is unknown inside apply."""
    assert "unknown" in _norm(answers.get("q6", "")), \
        f"q6: expected unknown, got {answers.get('q6')!r}"


def test_q7_fstring_prints_output_repr(answers):
    """f-string on an Output prints the Output object, not the value."""
    assert "output" in _norm(answers.get("q7", "")), \
        f"q7: expected output-repr, got {answers.get('q7')!r}"
